"""Modbus TCP simulator (own implementation so every frame can be logged and tampered with).
Units: 1 = PLC, 2 = energy meter (float32), 3 = VFD. Control API on :9102 (/_lab/*)."""
import asyncio, math, os, random, struct, time
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from labcommon import Lab

lab = Lab("modbus")
PORT = int(os.getenv("MODBUS_PORT", "502"))
T0 = time.time()
SIZE = 200
FC_NAMES = {1: "read_coils", 2: "read_discrete_inputs", 3: "read_holding_registers", 4: "read_input_registers",
            5: "write_single_coil", 6: "write_single_register", 15: "write_multiple_coils", 16: "write_multiple_registers"}
EXC = {1: "ILLEGAL_FUNCTION", 2: "ILLEGAL_DATA_ADDRESS", 3: "ILLEGAL_DATA_VALUE", 4: "SERVER_DEVICE_FAILURE",
       6: "SERVER_DEVICE_BUSY", 0x0A: "GATEWAY_PATH_UNAVAILABLE", 0x0B: "GATEWAY_TARGET_FAILED"}

units = {u: {"hr": [0] * SIZE, "co": [0] * SIZE, "di": [0] * SIZE} for u in (1, 2, 3)}
WRITABLE_HR = {1: {2}, 2: set(), 3: {3}}          # everything else is read-only -> exception 2 on write
units[1]["hr"][2] = 650                           # setpoint (65.0 C)
units[1]["co"][0] = 1                             # pump run
units[3]["hr"][3] = 5000                          # speed reference
conns = {}                                        # peer -> opened ts
counter32 = 123456


def order(b):
    """Arrange bytes into registers per the active byte-order fault (names as in PRTG's 'Byte Order' setting)."""
    mode = str(lab.fault("byte_order") or ("CDAB" if lab.fault("word_swap") else "ABCD")).upper()
    words = [b[i:i + 2] for i in range(0, len(b), 2)]
    if mode == "CDAB": words = words[::-1]                          # little-endian byte swap
    elif mode == "BADC": words = [x[::-1] for x in words]           # big-endian byte swap
    elif mode == "DCBA": words = [x[::-1] for x in words[::-1]]     # little-endian
    return [struct.unpack(">H", x)[0] for x in words]


def f32(v): return order(struct.pack(">f", v))


def update():
    global counter32
    t = time.time() - T0
    if lab.fault("freeze_values"):
        return
    u1, u2, u3 = units[1], units[2], units[3]
    temp = 60 + 8 * math.sin(t / 60) + random.uniform(-.3, .3)
    u1["hr"][0] = int(temp * 10)
    u1["hr"][1] = int((4.2 + .4 * math.sin(t / 25)) * 100)
    u1["hr"][3] = 1450 if u1["co"][0] else 0
    counter32 = (counter32 + (3 if u1["co"][0] else 0)) & 0xFFFFFFFF
    u1["hr"][4], u1["hr"][5] = counter32 >> 16, counter32 & 0xFFFF
    over = temp > 66
    u1["hr"][6] = (1 if u1["co"][0] else 0) | (2 if over else 0)
    u1["di"][0], u1["di"][1], u1["di"][2] = 1, 0, int(over)
    for i, v in enumerate((231.0 + math.sin(t / 9), 12.4 + 2 * math.sin(t / 17), 2.8 + .4 * math.sin(t / 17), 50.0 + .02 * math.sin(t / 5), counter32 / 10.0)):
        u2["hr"][i * 2], u2["hr"][i * 2 + 1] = f32(v)
    u2["hr"][12] = (-55 - int(5 * math.sin(t / 30))) & 0xFFFF            # signed int16 (-5.5 C x10)
    for i, r in enumerate(order(struct.pack(">d", 12345.6789 + t))): u2["hr"][20 + i] = r   # float64 at 20-23
    u3["hr"][0] = int(5000 * (1 if u1["co"][0] else 0) + 100 * math.sin(t / 7))
    u3["hr"][1] = int(85 + 10 * math.sin(t / 11))
    u3["hr"][2] = 0
    for u in (1, 2):
        pass


async def updater():
    while True:
        update()
        await asyncio.sleep(1)


def exc(fc, code):
    return bytes([fc | 0x80, code])


def process(unit, pdu):
    """returns (response_pdu or None, decoded-info dict)"""
    fc = pdu[0]
    info = {"fc": fc, "fc_name": FC_NAMES.get(fc, "unknown")}
    forced = lab.fault("exception", unit)
    if forced:
        info["injected"] = f"exception {forced}"
        return exc(fc, int(forced)), info
    dev = units.get(unit)
    if dev is None:
        if lab.fault("lenient_unit"):
            dev = units[1]
        else:
            return exc(fc, 0x0B), {**info, "note": "unknown unit id"}
    try:
        if fc in (1, 2, 3, 4):
            addr, cnt = struct.unpack(">HH", pdu[1:5]); info.update(addr=addr, count=cnt)
            bits = fc in (1, 2)
            if cnt < 1 or cnt > (2000 if bits else 125):
                return exc(fc, 3), info
            if addr + cnt > SIZE:
                return exc(fc, 2), info
            if bits:
                arr = dev["co" if fc == 1 else "di"][addr:addr + cnt]
                out = bytearray((cnt + 7) // 8)
                for i, b in enumerate(arr):
                    if b: out[i // 8] |= 1 << (i % 8)
                return bytes([fc, len(out)]) + bytes(out), info
            regs = dev["hr"][addr:addr + cnt]
            return bytes([fc, cnt * 2]) + b"".join(struct.pack(">H", r & 0xFFFF) for r in regs), info
        if fc == 5:
            addr, val = struct.unpack(">HH", pdu[1:5]); info.update(addr=addr, value=val)
            if val not in (0, 0xFF00): return exc(fc, 3), info
            if addr >= SIZE: return exc(fc, 2), info
            dev["co"][addr] = 1 if val else 0
            return pdu[:5], info
        if fc == 6:
            addr, val = struct.unpack(">HH", pdu[1:5]); info.update(addr=addr, value=val)
            if addr >= SIZE or addr not in WRITABLE_HR.get(unit, set()): return exc(fc, 2), info
            dev["hr"][addr] = val
            return pdu[:5], info
        if fc == 15:
            addr, cnt, bc = struct.unpack(">HHB", pdu[1:6]); info.update(addr=addr, count=cnt)
            if cnt < 1 or cnt > 1968 or bc != (cnt + 7) // 8: return exc(fc, 3), info
            if addr + cnt > SIZE: return exc(fc, 2), info
            for i in range(cnt): dev["co"][addr + i] = (pdu[6 + i // 8] >> (i % 8)) & 1
            return pdu[:5], info
        if fc == 16:
            addr, cnt, bc = struct.unpack(">HHB", pdu[1:6]); info.update(addr=addr, count=cnt)
            if cnt < 1 or cnt > 123 or bc != cnt * 2: return exc(fc, 3), info
            if addr + cnt > SIZE or any(a not in WRITABLE_HR.get(unit, set()) for a in range(addr, addr + cnt)): return exc(fc, 2), info
            for i in range(cnt): dev["hr"][addr + i] = struct.unpack(">H", pdu[6 + 2 * i:8 + 2 * i])[0]
            return pdu[:5], info
    except struct.error:
        return exc(fc, 3), {**info, "note": "short PDU"}
    return exc(fc, 1), info


async def handle(reader, writer):
    peer = "%s:%s" % writer.get_extra_info("peername")[:2]
    limit = lab.fault("max_connections")
    if limit and len(conns) >= int(limit):
        lab.log("connection_refused", peer=peer, reason=f"max_connections={limit}")
        writer.close(); return
    conns[peer] = time.time()
    lab.log("connect", peer=peer, open_connections=len(conns))
    idle = lab.fault("idle_timeout")
    try:
        while True:
            hdr = await asyncio.wait_for(reader.readexactly(7), timeout=float(idle) if idle else None)
            t0 = time.perf_counter()
            tid, pid, length, unit = struct.unpack(">HHHB", hdr)
            if pid != 0 or length < 2 or length > 254:
                lab.log("protocol_error", peer=peer, header=hdr.hex(" "), reason="bad MBAP header (protocol id/length)")
                break
            pdu = await reader.readexactly(length - 1)
            if lab.fault("drop_connection") and random.random() < float(lab.fault("drop_connection")):
                lab.log("injected_drop", peer=peer, tid=tid, req_hex=(hdr + pdu).hex(" "))
                break
            if lab.fault("no_response"):
                lab.log("injected_no_response", peer=peer, tid=tid, unit=unit, req_hex=(hdr + pdu).hex(" "))
                continue
            if lab.fault("delay_ms"):
                await asyncio.sleep(float(lab.fault("delay_ms")) / 1000)
            resp, info = process(unit, pdu)
            frame = struct.pack(">HHHB", tid, 0, len(resp) + 1, unit) + resp
            if lab.fault("garbage"):
                frame = struct.pack(">HHHB", tid, 0, len(resp) + 5, unit) + resp          # wrong length field
                info["injected"] = "wrong MBAP length"
            writer.write(frame); await writer.drain()
            e = resp[1] if resp[0] & 0x80 else None
            lab.log("request", peer=peer, tid=tid, unit=unit, **info, exception=(f"{e} {EXC.get(e, '')}" if e else None),
                    req_hex=(hdr + pdu).hex(" "), resp_hex=frame.hex(" "), latency_ms=round((time.perf_counter() - t0) * 1000, 2))
    except asyncio.IncompleteReadError:
        lab.log("disconnect", peer=peer, reason="client closed")
    except asyncio.TimeoutError:
        lab.log("disconnect", peer=peer, reason=f"idle timeout {idle}s (injected)")
    except ConnectionError as e:
        lab.log("disconnect", peer=peer, reason=str(e))
    finally:
        conns.pop(peer, None)
        writer.close()


@asynccontextmanager
async def lifespan(app):
    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    lab.log("started", modbus_port=PORT, units=list(units))
    task = asyncio.create_task(updater())
    yield
    task.cancel(); server.close()


app = FastAPI(title="modbus-sim", lifespan=lifespan)


def state():
    return {"connections": list(conns), "unit1_plc": {"temp_x10": units[1]["hr"][0], "pressure_x100": units[1]["hr"][1], "setpoint": units[1]["hr"][2],
            "rpm": units[1]["hr"][3], "status_word": units[1]["hr"][6], "coils": units[1]["co"][:3], "discrete_inputs": units[1]["di"][:3]},
            "unit2_meter_regs": units[2]["hr"][:24], "unit3_vfd_regs": units[3]["hr"][:4]}


lab.attach(app, state)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("CONTROL_PORT", "9102")), log_level="warning")
