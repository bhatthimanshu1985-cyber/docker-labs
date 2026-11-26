"""Mock REST APIs: FortiGate (FortiOS REST), Cisco IOS-XE RESTCONF, generic switch.
Which device an instance pretends to be is set by env DEVICE (fortigate|cisco-router|cisco-switch|switch)."""
import base64, math, os, time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

DEVICE = os.getenv("DEVICE", "fortigate")
FGT_TOKEN = os.getenv("FGT_TOKEN", "fgt-test-token")
CISCO_USER, CISCO_PASS = os.getenv("CISCO_USER", "admin"), os.getenv("CISCO_PASS", "admin")
T0 = time.time()
app = FastAPI(title=f"mock {DEVICE}")


def wave(base, amp, rate, lo=0, hi=100, phase=0.0):
    return round(min(hi, max(lo, base + amp * math.sin((time.time() - T0) * rate + phase))), 1)


def counter(bps):
    return int(bps * (time.time() - T0) + 5_000_000_000)


# ------------------------------------------------------------------ auth
@app.middleware("http")
async def auth(request: Request, call_next):
    p = request.url.path
    if p in ("/health", "/docs", "/openapi.json") or p.startswith("/prtg"):
        return await call_next(request)
    if DEVICE == "fortigate":
        tok = request.query_params.get("access_token") or request.headers.get("authorization", "").replace("Bearer ", "")
        if tok != FGT_TOKEN:
            return JSONResponse({"http_method": request.method, "status": "error", "http_status": 401, "error": 401}, 401)
    elif DEVICE.startswith("cisco"):
        h = request.headers.get("authorization", "")
        try:
            u, pw = base64.b64decode(h.split(" ", 1)[1]).decode().split(":", 1)
        except Exception:
            u = pw = None
        if (u, pw) != (CISCO_USER, CISCO_PASS):
            return JSONResponse({"ietf-restconf:errors": {"error": [{"error-type": "protocol", "error-tag": "access-denied"}]}}, 401,
                                headers={"WWW-Authenticate": "Basic"})
    return await call_next(request)


@app.get("/health")
def health(): return {"ok": True, "device": DEVICE}


# ------------------------------------------------------------------ metrics
def cpu():  return wave(22, 12, 0.07) if DEVICE == "fortigate" else wave(12, 5, 0.05)
def mem():  return wave(48, 5, 0.03) if DEVICE == "fortigate" else wave(30, 3, 0.03)
def sessions(): return int(wave(5200, 1500, 0.04, 0, 100000))


def interfaces():
    spec = {"fortigate": [("wan1", "203.0.113.2", True, 4_000_000, 1_500_000), ("wan2", "198.51.100.2", False, 0, 0),
                          ("lan", "192.168.1.1", True, 1_500_000, 4_000_000), ("dmz", "10.10.10.1", True, 200_000, 100_000)],
            "cisco-router": [("GigabitEthernet0/0/0", "10.0.0.1", True, 2_500_000, 1_200_000), ("GigabitEthernet0/0/1", "10.0.1.1", True, 900_000, 1_800_000),
                             ("GigabitEthernet0/0/2", "", False, 0, 0), ("Tunnel0", "172.16.0.1", True, 150_000, 120_000)],
            "cisco-switch": [(f"GigabitEthernet1/0/{n}", "", n not in (5, 9), 300_000 + n * 70_000, 200_000 + n * 40_000) for n in range(1, 13)],
            "switch": [(f"port{n}", "", n != 4, 200_000 + n * 50_000, 150_000 + n * 30_000) for n in range(1, 9)]}[DEVICE]
    return [dict(name=n, ip=ip, up=up, rx=counter(rx) if up else 0, tx=counter(tx) if up else 0) for n, ip, up, rx, tx in spec]


# ------------------------------------------------------------------ FortiGate (FortiOS REST)
def fgt(results, **extra):
    return {"http_method": "GET", "results": results, "vdom": "root", "status": "success", "http_status": 200,
            "serial": "FGT60FTK00000001", "version": "v7.2.5", "build": 1517, **extra}


@app.get("/api/v2/monitor/system/status")
def fgt_status():
    return fgt({"model_name": "FortiGate", "model_number": "60F", "model": "FGT60F", "hostname": "FGT-LAB-01", "log_disk_status": "available"},
               )


@app.get("/api/v2/monitor/system/resource/usage")
def fgt_usage():
    return fgt({"cpu": [{"current": cpu()}], "mem": [{"current": mem()}], "session": [{"current": sessions()}],
                "setup_rate": [{"current": int(wave(180, 60, 0.09, 0, 5000))}], "disk": [{"current": wave(31, 1, 0.01)}]})


@app.get("/api/v2/monitor/system/interface")
def fgt_if():
    return fgt({i["name"]: {"id": i["name"], "name": i["name"], "ip": i["ip"], "link": i["up"], "speed": 1000 if i["up"] else 0,
                            "rx_bytes": i["rx"], "tx_bytes": i["tx"], "rx_errors": 0, "tx_errors": 0} for i in interfaces()})


@app.get("/api/v2/monitor/vpn/ipsec")
def fgt_vpn():
    return fgt([{"name": "Site-to-HQ", "rgwy": "192.0.2.10", "status": "up", "incoming_bytes": counter(90_000), "outgoing_bytes": counter(70_000)},
                {"name": "Site-to-Branch", "rgwy": "192.0.2.20", "status": "down", "incoming_bytes": 0, "outgoing_bytes": 0}])


@app.get("/api/v2/monitor/system/ha-peer")
def fgt_ha(): return fgt([{"serial_no": "FGT60FTK00000001", "hostname": "FGT-LAB-01", "primary": True, "status": "up"}])


@app.get("/api/v2/cmdb/firewall/policy")
def fgt_pol():
    return fgt([{"policyid": 1, "name": "LAN-to-WAN", "srcintf": [{"name": "lan"}], "dstintf": [{"name": "wan1"}], "action": "accept", "status": "enable"},
                {"policyid": 2, "name": "DMZ-in", "srcintf": [{"name": "wan1"}], "dstintf": [{"name": "dmz"}], "action": "accept", "status": "enable"}])


# ------------------------------------------------------------------ Cisco IOS-XE RESTCONF
YANG = "application/yang-data+json"


def yang(body): return JSONResponse(body, media_type=YANG)


@app.get("/restconf/data/Cisco-IOS-XE-native:native/hostname")
def cx_host(): return yang({"Cisco-IOS-XE-native:hostname": "RTR-LAB-01" if DEVICE == "cisco-router" else "SW-LAB-01"})


@app.get("/restconf/data/Cisco-IOS-XE-native:native/version")
def cx_ver(): return yang({"Cisco-IOS-XE-native:version": "17.6"})


@app.get("/restconf/data/Cisco-IOS-XE-process-cpu-oper:cpu-usage/cpu-utilization")
def cx_cpu():
    return yang({"Cisco-IOS-XE-process-cpu-oper:cpu-utilization": {"five-seconds": int(cpu()), "one-minute": int(wave(12, 4, 0.05)), "five-minutes": int(wave(11, 2, 0.02))}})


@app.get("/restconf/data/Cisco-IOS-XE-memory-oper:memory-statistics/memory-statistic")
def cx_mem():
    used = int(wave(1_200_000_000, 80_000_000, 0.03, 0, 4e9)); total = 4_000_000_000
    return yang({"Cisco-IOS-XE-memory-oper:memory-statistic": [{"name": "Processor", "total-memory": total, "used-memory": used, "free-memory": total - used}]})


@app.get("/restconf/data/ietf-interfaces:interfaces-state/interface")
def cx_if():
    return yang({"ietf-interfaces:interface": [{"name": i["name"], "type": "iana-if-type:ethernetCsmacd", "admin-status": "up",
                 "oper-status": "up" if i["up"] else "down", "speed": 1000000000,
                 "statistics": {"in-octets": i["rx"], "out-octets": i["tx"], "in-errors": 0, "out-errors": 0}} for i in interfaces()]})


@app.get("/restconf/data/Cisco-IOS-XE-environment-oper:environment-sensors/environment-sensor")
def cx_env():
    return yang({"Cisco-IOS-XE-environment-oper:environment-sensor": [{"name": "Chassis Temperature", "location": "Switch 1", "state": "Normal",
                 "current-reading": int(wave(38, 3, 0.01, 0, 120)), "sensor-units": "Celsius"}]})


# ------------------------------------------------------------------ generic switch
@app.get("/api/status")
def sw_status():
    return {"hostname": "SW-ACCESS-02", "model": "24-port GbE managed switch", "uptime_s": int(time.time() - T0) + 8_640_000,
            "temperature_c": wave(41, 3, 0.01, 0, 120), "ports": [{"name": i["name"], "link": i["up"], "rx_bytes": i["rx"], "tx_bytes": i["tx"]} for i in interfaces()]}


# ------------------------------------------------------------------ PRTG "REST Custom v2" ready JSON (no auth)
@app.get("/prtg/sensors")
def prtg():
    ifs = interfaces()
    res = [{"channel": "CPU", "value": cpu(), "unit": "Percent", "float": 1}, {"channel": "Memory", "value": mem(), "unit": "Percent", "float": 1},
           {"channel": "Interfaces up", "value": sum(i["up"] for i in ifs)}, {"channel": "Interfaces down", "value": sum(not i["up"] for i in ifs)}]
    if DEVICE == "fortigate":
        res += [{"channel": "Sessions", "value": sessions()}, {"channel": "IPsec tunnels up", "value": 1}]
    if DEVICE != "switch":
        res.append({"channel": "Temperature", "value": wave(38, 3, 0.01, 0, 120), "unit": "Temperature", "float": 1})
    return {"prtg": {"result": res, "text": f"{DEVICE} simulated"}}
