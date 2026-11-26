"""Mock REST APIs: FortiGate (FortiOS REST), Cisco IOS-XE RESTCONF, generic switch.
Which device an instance pretends to be is set by env DEVICE (fortigate|cisco-router|cisco-switch|switch)."""
import asyncio, base64, math, os, random, sys, time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

sys.path.insert(0, os.getenv("SIMCORE_PATH", "/srv"))
from simcore import SIM

DEVICE = os.getenv("DEVICE", "fortigate")
FGT_TOKEN = os.getenv("FGT_TOKEN", "fgt-test-token")
CISCO_USER, CISCO_PASS = os.getenv("CISCO_USER", "admin"), os.getenv("CISCO_PASS", "admin")
T0 = time.time()
app = FastAPI(title=f"mock {DEVICE}")


IPS = {"wan1": "203.0.113.2", "wan2": "198.51.100.2", "lan": "192.168.1.1", "dmz": "10.10.10.1", "ssl.root": "",
       "GigabitEthernet0/0/0": "10.0.0.1", "GigabitEthernet0/0/1": "10.0.1.1", "Tunnel0": "172.16.0.1"}
VERBOSE = os.getenv("API_LOG", "1") == "1"


# ------------------------------------------------------------------ auth
@app.middleware("http")
async def behaviour(request: Request, call_next):
    """network behaviour of the simulated device: unreachable/outage/reboot -> hang then 504, loss -> 504, latency"""
    n = SIM.net(DEVICE)
    if VERBOSE:
        print(f"[{DEVICE}] {request.method} {request.url.path}?{request.url.query}", flush=True)
    if n["down"]:
        await asyncio.sleep(20)
        return JSONResponse({"error": "gateway timeout (device unreachable)"}, 504)
    if n["loss_pct"] and random.random() * 100 < n["loss_pct"]:
        await asyncio.sleep(10)
        return JSONResponse({"error": "gateway timeout"}, 504)
    lo, hi = n["latency_ms"]
    await asyncio.sleep(random.uniform(lo, hi) / 1000)
    return await call_next(request)


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


# ------------------------------------------------------------------ metrics (all from simcore, same values SNMP serves)
def cpu(): return round(SIM.cpu(DEVICE), 1)
def mem(): return round(SIM.mem(DEVICE), 1)
def sessions(): return SIM.sessions(DEVICE)


def interfaces():
    out = []
    for name in SIM.dev(DEVICE).get("interfaces", {}):
        v = SIM.iface(DEVICE, name)
        out.append(dict(name=name, ip=IPS.get(name, ""), up=v["up"], rx=v["in_oct"], tx=v["out_oct"], rxe=v["in_err"], txe=v["out_err"],
                        rxd=v["in_disc"], txd=v["out_disc"], rxbps=v["in_bps"], txbps=v["out_bps"],
                        speed=SIM.iface_cfg(DEVICE, name).get("speed", 0)))
    return out


def uptime_s(): return int(SIM.uptime_ticks(DEVICE) / 100)


# ------------------------------------------------------------------ FortiGate (FortiOS REST)
SERIAL = "FGT60FTK00000001"


def fgt(results, **extra):
    return {"http_method": "GET", "results": results, "vdom": "root", "status": "success", "http_status": 200,
            "serial": SERIAL, "version": "v7.2.5", "build": 1517, **extra}


def hist(fn, windows=((60, "1-min"), (600, "10-min"), (1800, "30-min"))):
    now, out = time.time(), {}
    for w, label in windows:
        xs = [fn(now - w * i / 8) for i in range(8)]
        out[label] = {"min": min(xs), "max": max(xs), "average": round(sum(xs) / len(xs))}
    return out


@app.get("/api/v2/monitor/system/status")
def fgt_status():
    return fgt({"model_name": "FortiGate", "model_number": "60F", "model": "FGT60F", "hostname": "FGT-LAB-01", "log_disk_status": "available",
                "uptime": uptime_s()}, path="system", name="status", action="")


@app.get("/api/v2/monitor/system/time/select")
def fgt_time():
    t = time.time(); lt = time.localtime(t)
    return fgt({"time": int(t), "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S", lt), "timezone": time.strftime("%Z", lt), "year": lt.tm_year,
                "month": lt.tm_mon, "day": lt.tm_mday, "hour": lt.tm_hour, "minute": lt.tm_min, "second": lt.tm_sec}, path="system", name="time", action="select")


@app.get("/api/v2/cmdb/system/vdom")
def fgt_vdom():
    return fgt([{"name": "root", "short-name": "root", "q_origin_key": "root", "flag": 0, "temporary": 0}], path="system", name="vdom")


@app.get("/api/v2/monitor/web-ui/state")
def fgt_webui(scope: str = "global"):
    now = int(time.time() * 1000)
    return fgt({"snapshot_utc_time": now, "utc_last_reboot": now - uptime_s() * 1000, "time_zone_offset": time.timezone // -60,
                "forticare_registered": False, "model_name": "FortiGate", "model_number": "60F", "hostname": "FGT-LAB-01",
                "cpu": round(SIM.cpu(DEVICE)), "mem": round(SIM.mem(DEVICE)), "memory": round(SIM.mem(DEVICE)),
                "disk": round(26 + 0.02 * uptime_s() / 86400), "session": SIM.sessions(DEVICE), "sessions": SIM.sessions(DEVICE),
                "setup_rate": SIM.session_rate(DEVICE),
                # 0 = normal; >0 when memory pressure is high (memory-leak scenario)
                "conserve_mode": 1 if SIM.mem(DEVICE) > 88 else 0, "conserve_mode_status": "off" if SIM.mem(DEVICE) <= 88 else "on"}, path="web-ui", name="state")


@app.get("/api/v2/monitor/system/firmware")
def fgt_fw():
    return fgt({"current": {"platform-id": "FGT60F", "major": 7, "minor": 2, "patch": 5, "build": 1517, "version": "v7.2.5", "release-type": "GA"}})


@app.get("/api/v2/monitor/system/resource/usage")
def fgt_usage(request: Request):
    """FortiOS system resource usage: cpu, mem, disk, session, setup_rate (+ ipv6/npu counterparts) with 1/10/30-min history"""
    t = time.time()
    r = {"cpu": [{"current": round(SIM.cpu(DEVICE, t)), "historical": hist(lambda x: round(SIM.cpu(DEVICE, x)))}],
         "mem": [{"current": round(SIM.mem(DEVICE, t)), "historical": hist(lambda x: round(SIM.mem(DEVICE, x)))}],
         "disk": [{"current": round(26 + 0.02 * uptime_s() / 86400)}],
         "session": [{"current": SIM.sessions(DEVICE, t), "historical": hist(lambda x: SIM.sessions(DEVICE, x))}],
         "setup_rate": [{"current": SIM.session_rate(DEVICE, t), "historical": hist(lambda x: SIM.session_rate(DEVICE, x))}],
         "session6": [{"current": 0}], "setup_rate6": [{"current": 0}], "npu_session": [{"current": 0}],
         "faz_log_rate": [{"current": 0}], "fds_log_rate": [{"current": 0}]}
    res = request.query_params.get("resource")
    if res:
        r = {k: v for k, v in r.items() if k in res.split(",")}
    return fgt(r, path="system", name="resource", action="usage")


@app.get("/api/v2/monitor/system/performance/status")
def fgt_perf():
    c = SIM.cpu_cores(DEVICE, time.time())
    return fgt({"cpu": {"user": round(SIM.cpu(DEVICE) * 0.6), "system": round(SIM.cpu(DEVICE) * 0.3), "nice": 0, "idle": round(100 - SIM.cpu(DEVICE)),
                        "iowait": 0, "irq": 0, "softirq": round(SIM.cpu(DEVICE) * 0.1)},
                "cores": [round(x) for x in c], "mem": {"total": 4_000_000_000, "used": int(SIM.mem(DEVICE) / 100 * 4e9)},
                "uptime": uptime_s(), "session": SIM.sessions(DEVICE)})


@app.get("/api/v2/monitor/system/interface")
def fgt_if():
    return fgt({i["name"]: {"id": i["name"], "name": i["name"], "ip": i["ip"], "mask": 24, "link": i["up"], "speed": (i["speed"] // 1_000_000) if i["up"] else 0,
                            "duplex": 1, "tx_packets": i["tx"] // 800, "rx_packets": i["rx"] // 800, "tx_bytes": i["tx"], "rx_bytes": i["rx"],
                            "tx_errors": i["txe"], "rx_errors": i["rxe"]} for i in interfaces()}, path="system", name="interface")


def _vpn_list():
    out = []
    for n, (name, v) in enumerate(SIM.dev(DEVICE).get("vpn", {}).items(), 1):
        s = SIM.vpn(DEVICE, name)
        up = s["up"]
        px = {"proxy_src": [{"subnet": f"10.{n}.0.0/16", "port": 0, "protocol": 0, "protocol_name": "all"}],
              "proxy_dst": [{"subnet": f"172.16.{n}.0/24", "port": 0, "protocol": 0, "protocol_name": "all"}],
              "status": "up" if up else "down", "p2name": name, "p2serial": n, "expire": 3600 if up else 0,
              "incoming_bytes": s["in"], "outgoing_bytes": s["out"]}
        out.append({"proxyid": [px], "name": name, "comments": "", "wizard-type": "custom", "connection_count": 1 if up else 0,
                    "creation_time": int(time.time()) - 86400 if up else 0, "username": "", "type": "automatic",
                    "incoming_bytes": s["in"], "outgoing_bytes": s["out"], "rgwy": v.get("remote", "192.0.2.10"), "tun_id": f"10.0.0.{n}", "tun_id6": "::"})
    return out


@app.get("/api/v2/monitor/vpn/ipsec")
def fgt_vpn():
    return fgt(_vpn_list(), path="vpn", name="ipsec")


def _ssl_users():
    n = SIM.ssl_users(DEVICE)
    return [{"user_name": f"vpnuser{i + 1}", "user_group": "SSL-VPN-Users", "remote_host": f"203.0.113.{10 + i}", "last_login_time": int(time.time()) - 600 * (i + 1),
             "auth_type": 1, "subsessions": [{"aip": f"10.212.134.{200 + i}", "in_bytes": 120000 * (i + 1), "out_bytes": 480000 * (i + 1), "type": "tunnel"}]} for i in range(n)]


@app.get("/api/v2/monitor/vpn/ssl")
def fgt_ssl(): return fgt(_ssl_users(), path="vpn", name="ssl")


@app.get("/api/v2/monitor/vpn/ssl/stats")
def fgt_ssl_stats():
    n = SIM.ssl_users(DEVICE)
    return fgt({"user_count": n, "max_users": 50, "web_mode_connections": 0, "tunnel_mode_connections": n, "tunnel_users": n})


@app.get("/api/v2/monitor/system/ha-peer")
def fgt_ha(): return fgt([{"serial_no": SERIAL, "hostname": "FGT-LAB-01", "primary": True, "status": "up"}])


@app.get("/api/v2/monitor/firewall/session/summary")
def fgt_ses():
    n = SIM.sessions(DEVICE)
    return fgt({"session_count": n, "setup_rate": SIM.session_rate(DEVICE), "tcp": int(n * 0.78), "udp": int(n * 0.2), "icmp": int(n * 0.02)})


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
    t = time.time()
    return yang({"Cisco-IOS-XE-process-cpu-oper:cpu-utilization": {"five-seconds": round(SIM.cpu(DEVICE, t)), "one-minute": round(SIM.cpu_avg(DEVICE, t, 60)),
                                                                   "five-minutes": round(SIM.cpu_avg(DEVICE, t, 300))}})


@app.get("/restconf/data/Cisco-IOS-XE-memory-oper:memory-statistics/memory-statistic")
def cx_mem():
    total = 4_000_000_000; used = int(SIM.mem(DEVICE) / 100 * total)
    return yang({"Cisco-IOS-XE-memory-oper:memory-statistic": [{"name": "Processor", "total-memory": total, "used-memory": used, "free-memory": total - used}]})


@app.get("/restconf/data/ietf-interfaces:interfaces-state/interface")
def cx_if():
    return yang({"ietf-interfaces:interface": [{"name": i["name"], "type": "iana-if-type:ethernetCsmacd", "admin-status": "up",
                 "oper-status": "up" if i["up"] else "down", "speed": i["speed"],
                 "statistics": {"in-octets": i["rx"], "out-octets": i["tx"], "in-errors": i["rxe"], "out-errors": i["txe"],
                                "in-discards": i["rxd"], "out-discards": i["txd"]}} for i in interfaces()]})


@app.get("/restconf/data/Cisco-IOS-XE-environment-oper:environment-sensors/environment-sensor")
def cx_env():
    return yang({"Cisco-IOS-XE-environment-oper:environment-sensor": [{"name": "Chassis Temperature", "location": "Switch 1", "state": "Normal",
                 "current-reading": round(SIM.temp(DEVICE)), "sensor-units": "Celsius"}]})


# ------------------------------------------------------------------ generic switch
@app.get("/api/status")
def sw_status():
    return {"hostname": "SW-ACCESS-02", "model": "24-port GbE managed switch", "uptime_s": uptime_s(),
            "temperature_c": round(SIM.temp(DEVICE), 1), "ports": [{"name": i["name"], "link": i["up"], "rx_bytes": i["rx"], "tx_bytes": i["tx"],
                                                                      "rx_errors": i["rxe"], "tx_errors": i["txe"]} for i in interfaces()]}


# ------------------------------------------------------------------ PRTG "REST Custom v2" ready JSON (no auth)
# NOTE: existing sensors read channels by position, so new channels are only ever appended.
@app.get("/prtg/sensors")
def prtg():
    ifs = interfaces()
    res = [{"channel": "CPU", "value": cpu(), "unit": "Percent", "float": 1}, {"channel": "Memory", "value": mem(), "unit": "Percent", "float": 1},
           {"channel": "Interfaces up", "value": sum(i["up"] for i in ifs)}, {"channel": "Interfaces down", "value": sum(not i["up"] for i in ifs)}]
    if DEVICE == "fortigate":
        res += [{"channel": "Sessions", "value": sessions()}, {"channel": "IPsec tunnels up", "value": sum(v["up"] for v in (SIM.vpn(DEVICE, n) for n in SIM.dev(DEVICE).get("vpn", {})))}]
    if DEVICE != "switch":
        res.append({"channel": "Temperature", "value": round(SIM.temp(DEVICE), 1), "unit": "Temperature", "float": 1})
    res.append({"channel": "Uptime", "value": uptime_s(), "unit": "TimeSeconds"})
    res.append({"channel": "Errors total", "value": sum(i["rxe"] + i["txe"] for i in ifs), "mode": "Difference"})
    return {"prtg": {"result": res, "text": f"{DEVICE} simulated"}}


# FortiOS documents most monitor endpoints with a trailing /select; accept both forms
from fastapi.routing import APIRoute
for _r in list(app.routes):
    if isinstance(_r, APIRoute) and _r.path.startswith("/api/v2/monitor/") and not _r.path.endswith("/select"):
        app.add_api_route(_r.path + "/select", _r.endpoint, methods=["GET"])
