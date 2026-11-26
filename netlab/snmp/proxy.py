"""UDP front-end for the SNMP simulator.  Listens on the public SNMP port, reads the v1/v2c community string to find
out which simulated device is addressed, then applies that device's *network behaviour* from scenarios.json
(unreachable/outage/reboot window -> silently drop, packet loss %, latency + jitter, control-plane rate limit)
before forwarding to the real snmpsim backend.  SNMPv3 packets are forwarded untouched."""
import asyncio, os, random, sys, time

sys.path.insert(0, os.getenv("SIMCORE_PATH", "/srv"))
from simcore import SIM

LISTEN = (os.getenv("PROXY_HOST", "0.0.0.0"), int(os.getenv("PROXY_PORT", "161")))
BACKEND = ("127.0.0.1", int(os.getenv("BACKEND_PORT", "16100")))
VERBOSE = os.getenv("PROXY_LOG", "0") == "1"


def community(pkt: bytes):
    """minimal BER walk: SEQUENCE { INTEGER version, OCTET STRING community, ... } -> (version, community) or None"""
    try:
        def tl(i):
            tag, ln = pkt[i], pkt[i + 1]
            if ln & 0x80:
                n = ln & 0x7F
                ln = int.from_bytes(pkt[i + 2:i + 2 + n], "big")
                return tag, ln, i + 2 + n
            return tag, ln, i + 2
        tag, _, i = tl(0)
        if tag != 0x30: return None
        tag, ln, i = tl(i)
        if tag != 0x02: return None
        ver = int.from_bytes(pkt[i:i + ln], "big")
        i += ln
        tag, ln, i = tl(i)
        if tag != 0x04 or ver not in (0, 1): return None
        return ver, pkt[i:i + ln].decode("latin1")
    except Exception:
        return None


class Bucket:
    def __init__(self): self.t, self.n = 0, 0.0


class Front(asyncio.DatagramProtocol):
    def __init__(self):
        self.buckets = {}
        self.cache = {}

    def connection_made(self, transport): self.tr = transport

    def net(self, dev):
        now = time.time()
        c = self.cache.get(dev)
        if not c or now - c[0] > 1.0:
            c = (now, SIM.net(dev, now)); self.cache[dev] = c
        return c[1]

    def datagram_received(self, data, addr):
        asyncio.ensure_future(self.handle(data, addr))

    async def handle(self, data, addr):
        c = community(data)
        delay = 0.0
        if c and c[1] in SIM.conf().get("devices", {}):
            dev = c[1]
            n = self.net(dev)
            if n["down"]:
                if VERBOSE: print(f"{dev}: unreachable -> drop", flush=True)
                return
            if n["loss_pct"] and random.random() * 100 < n["loss_pct"]:
                return
            rl = n.get("rate_limit_per_s", 0)
            if rl:
                b = self.buckets.setdefault(dev, Bucket()); now = time.time()
                b.n = min(rl, b.n + (now - b.t) * rl); b.t = now
                if b.n < 1: return
                b.n -= 1
            lo, hi = n["latency_ms"]
            delay = (random.uniform(lo, hi) + (random.expovariate(1 / max(1.0, (hi - lo) / 3)) if random.random() < 0.05 else 0)) / 1000
        loop = asyncio.get_running_loop()
        fut = loop.create_future()

        class Back(asyncio.DatagramProtocol):
            def datagram_received(s, d, a):
                if not fut.done(): fut.set_result(d)
        tr, _ = await loop.create_datagram_endpoint(Back, remote_addr=BACKEND)
        try:
            tr.sendto(data)
            reply = await asyncio.wait_for(fut, 5)
        except asyncio.TimeoutError:
            return
        finally:
            tr.close()
        if delay: await asyncio.sleep(delay)
        self.tr.sendto(reply, addr)


async def main():
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(Front, local_addr=LISTEN)
    print(f"snmp front-end on {LISTEN} -> backend {BACKEND}", flush=True)
    await asyncio.Event().wait()

asyncio.run(main())
