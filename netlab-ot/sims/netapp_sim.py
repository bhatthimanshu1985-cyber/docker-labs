"""NetApp ONTAP simulator: ONTAP REST API (/api/...) and a minimal ZAPI/ONTAPI endpoint, HTTP :8080 and HTTPS :443.
Every request/response is logged. Faults/actions via /_lab/*  (same port)."""
import asyncio, base64, math, os, time, uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from labcommon import Lab

lab = Lab("netapp")
T0 = time.time()
USER, PASSWORD = os.getenv("ONTAP_USER", "admin"), os.getenv("ONTAP_PASS", "netapp123")
TB, GB = 1024 ** 4, 1024 ** 3
U = lambda s: str(uuid.uuid5(uuid.NAMESPACE_DNS, s))

CLUSTER = "labcluster01"
NODES = ["labcluster01-01", "labcluster01-02"]
# name, node, size, used_at_start, growth bytes/hour
AGGRS = {"aggr1_n1": (NODES[0], 20 * TB, 11.0 * TB, 2 * GB), "aggr1_n2": (NODES[1], 20 * TB, 9.2 * TB, 1 * GB), "aggr0_n1": (NODES[0], 1 * TB, 0.12 * TB, 0)}
# name, svm, aggr, size, used_at_start, growth/h, type
VOLS = {"vol_data01": ("svm_nfs", "aggr1_n1", 4 * TB, 2.9 * TB, 3 * GB), "vol_db01": ("svm_nfs", "aggr1_n1", 2 * TB, 1.4 * TB, 6 * GB),
        "vol_cifs_home": ("svm_cifs", "aggr1_n2", 3 * TB, 1.1 * TB, 2 * GB), "vol_vmware_ds1": ("svm_nfs", "aggr1_n2", 6 * TB, 4.8 * TB, 4 * GB),
        "vol_backup": ("svm_cifs", "aggr1_n2", 8 * TB, 3.0 * TB, 5 * GB), "svm_nfs_root": ("svm_nfs", "aggr1_n1", 1 * GB, 1e6, 0),
        "svm_cifs_root": ("svm_cifs", "aggr1_n2", 1 * GB, 1e6, 0)}
DISKS = [f"1.0.{i}" for i in range(24)]
ems = []


def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_ems(name, sev, msg, node=NODES[0]):
    ems.append({"index": len(ems) + 1, "time": now_iso(), "node": {"name": node}, "message": {"name": name, "severity": sev}, "log_message": f"{name}: {msg}"})


add_ems("callhome.weekly", "notice", "Weekly AutoSupport sent.")
add_ems("kern.uptime.filer", "informational", "up for 41 days.")


def hrs(): return (time.time() - T0) / 3600


def wave(base, amp, rate, phase=0): return base + amp * math.sin((time.time() - T0) * rate + phase)


# ---------------------------------------------------------------- model (computed live so faults apply immediately)
def node_state(n): return "down" if lab.fault("node_down", n) else "up"


def aggr_used(a):
    node, size, used, g = AGGRS[a]
    if lab.fault("aggr_full", a): return size * 0.965
    return min(size * .995, used + g * hrs())


def vol_used(v):
    svm, ag, size, used, g = VOLS[v]
    if lab.fault("volume_full", v): return size * 0.985
    return min(size, used + g * hrs())


def vol_state(v): return "offline" if lab.fault("volume_offline", v) else "online"


def aggr_rec(a):
    node, size, _, _ = AGGRS[a]; used = aggr_used(a)
    return {"uuid": U(a), "name": a, "node": {"name": node, "uuid": U(node)}, "state": "online" if node_state(node) == "up" else "offline",
            "home_node": {"name": node}, "space": {"block_storage": {"size": int(size), "available": int(size - used), "used": int(used),
            "full_threshold_percent": 98}, "efficiency": {"savings": int(used * .2), "ratio": 1.25}},
            "data_encryption": {"software_encryption_enabled": False}, "snaplock_type": "non_snaplock",
            "block_storage": {"primary": {"disk_count": 8 if a.startswith("aggr0") else 20, "raid_type": "raid_dp", "disk_class": "solid_state", "raid_size": 24},
                              "storage_type": "ssd", "mirror": {"enabled": False}},
            "inode_attributes": {"files_total": 10 ** 7, "files_used": 120000, "max_files_available": 10 ** 7, "max_files_possible": 2 * 10 ** 9}}


def raw(v, k):
    e = time.time() - T0 + 1_000_000
    ops = int(e * k)
    return {"timestamp": now_iso(), "status": "ok", "iops_raw": {"read": int(ops * .7), "write": int(ops * .3), "other": int(e * 3), "total": ops + int(e * 3)},
            "latency_raw": {"read": int(ops * .7 * 400), "write": int(ops * .3 * 560), "other": int(e * 3 * 200), "total": int(ops * 440)},
            "throughput_raw": {"read": int(ops * .7 * 8192), "write": int(ops * .3 * 4096), "other": 0, "total": int(ops * 6963)}}


def vol_rec(v, want_metrics=False, want_stats=False):
    svm, ag, size, _, _ = VOLS[v]; used = vol_used(v)
    r = {"uuid": U(v), "name": v, "svm": {"name": svm, "uuid": U(svm)}, "state": vol_state(v), "type": "rw", "style": "flexvol",
         "aggregates": [{"name": ag, "uuid": U(ag)}], "nas": {"path": f"/{v}"},
         "space": {"size": int(size), "available": int(size - used), "used": int(used), "snapshot": {"used": int(used * .05), "reserve_percent": 5},
                   "percent_used": round(used * 100 / size, 1)}, "snapmirror": {"is_protected": v in ("vol_data01", "vol_db01")},
         "files": {"maximum": int(size / 4096), "used": int(used / 65536) + 96},
         "autosize": {"mode": "off", "maximum": int(size * 1.2), "minimum": int(size), "grow_threshold": 85, "shrink_threshold": 50},
         "snapshot_policy": {"name": "default"}, "language": "c.utf_8", "create_time": "2025-03-14T09:12:44+00:00"}
    if want_metrics:
        lat = 400 + (int(lab.fault("high_latency", v) or 0) * 1000 if lab.fault("high_latency", v) else 0) + int(wave(0, 80, .3))
        iops = int(wave(1800, 600, .05)) if r["state"] == "online" else 0
        r["metrics"] = {"timestamp": now_iso(), "status": "ok", "duration": "PT15S", "iops": {"read": int(iops * .7), "write": int(iops * .3), "other": 40, "total": iops + 40},
                        "latency": {"read": lat, "write": int(lat * 1.4), "other": int(lat * .5), "total": int(lat * 1.1)},
                        "throughput": {"read": iops * 8192, "write": iops * 4096, "other": 0, "total": iops * 12288}}
    if want_stats:
        r["statistics"] = raw(v, 1800 if r["state"] == "online" else 0)
    return r


def disk_rec(d):
    broken = lab.fault("disk_fail", d)
    n = NODES[0] if int(d.split(".")[2]) < 12 else NODES[1]
    return {"name": d, "uid": U(d), "serial_number": "S3" + d.replace(".", ""), "model": "X371_S163A960ATE", "type": "ssd", "usable_size": 960 * 10 ** 9,
            "state": "broken" if broken else "present", "container_type": "broken" if broken else "aggregate", "node": {"name": n}, "bay": int(d.split(".")[2])}


def ports():
    out = []
    for n in NODES:
        for p in ("e0a", "e0b", "e0c", "e0d"):
            up = node_state(n) == "up" and not lab.fault("port_down", f"{n}:{p}") and not (p == "e0d")
            out.append({"name": p, "node": {"name": n}, "type": "physical", "state": "up" if up else "down", "speed": 10000 if up else 0, "mtu": 9000 if p == "e0c" else 1500,
                        "enabled": True})
    return out


def snapmirror():
    broken = lab.fault("snapmirror_broken")
    lag = 3 * 3600 + 120 if not lab.fault("snapmirror_lag") else int(lab.fault("snapmirror_lag")) * 3600
    return [{"uuid": U("sm1"), "source": {"path": "svm_nfs:vol_data01", "svm": {"name": "svm_nfs"}}, "destination": {"path": "svm_dr:vol_data01_dr", "svm": {"name": "svm_dr"}},
             "state": "broken_off" if broken else "snapmirrored", "healthy": not broken and lag < 86400, "lag_time": f"PT{lag // 3600}H{lag % 3600 // 60}M",
             "unhealthy_reason": [{"message": "Transfer failed.", "code": "6619546"}] if broken else []}]


def on_fault(name, target, value):
    if name == "volume_full": add_ems("wafl.vol.full", "alert", f"Volume {target} is full (98%).")
    if name == "aggr_full": add_ems("monitor.volume.nearlyFull", "alert", f"Aggregate {target} is nearly full (96%).")
    if name == "volume_offline": add_ems("wafl.vol.offline", "error", f"Volume {target} is now offline.")
    if name == "disk_fail": add_ems("disk.failed", "alert", f"Disk {target} failed. RAID reconstruction started.")
    if name == "node_down": add_ems("ha.takeoverComplete", "alert", f"Node {target} is down. Partner takeover complete.", NODES[1] if target == NODES[0] else NODES[0])
    if name == "snapmirror_broken": add_ems("snapmirror.dp.xfer.failed", "error", "SnapMirror transfer to svm_dr:vol_data01_dr failed.")


app = FastAPI(title="netapp-sim", docs_url=None, redoc_url=None, openapi_url=None)
lab.attach(app, lambda: {"aggregates": {a: f"{aggr_used(a) * 100 / AGGRS[a][1]:.1f}%" for a in AGGRS},
                         "volumes": {v: f"{vol_state(v)} {vol_used(v) * 100 / VOLS[v][2]:.1f}%" for v in VOLS}, "nodes": {n: node_state(n) for n in NODES}, "ems_events": len(ems)},
           on_fault=on_fault)


@app.middleware("http")
async def wrap(request: Request, call_next):
    if request.url.path.startswith("/_lab"):
        return await call_next(request)
    t0 = time.perf_counter()
    body = (await request.body()).decode(errors="replace")[:2000]
    hdr = {k: ("<redacted>" if k == "authorization" else v) for k, v in request.headers.items() if k in ("authorization", "accept", "content-type", "user-agent")}
    status, note = None, None
    if lab.fault("api_delay_ms"):
        await asyncio.sleep(float(lab.fault("api_delay_ms")) / 1000); note = f"injected delay {lab.fault('api_delay_ms')}ms"
    ok = False
    try:
        u, p = base64.b64decode(request.headers.get("authorization", "").split(" ", 1)[1]).decode().split(":", 1)
        ok = (u, p) == (USER, PASSWORD)
    except Exception:
        pass
    if lab.fault("auth_fail") or not ok:
        resp = JSONResponse({"error": {"message": "User is not authorized", "code": "6", "target": "authorization"}}, 401, headers={"WWW-Authenticate": "Basic"})
        note = (note or "") + (" auth failure injected" if ok else " bad/missing credentials")
    elif lab.fault("api_error"):
        resp = JSONResponse({"error": {"message": "Internal error. Failed to process request.", "code": "4"}}, int(lab.fault("api_error")))
        note = (note or "") + f" injected HTTP {lab.fault('api_error')}"
    else:
        resp = await call_next(request)
    chunks = [c async for c in resp.body_iterator] if hasattr(resp, "body_iterator") else [resp.body]
    data = b"".join(chunks)
    lab.log("request", client=request.client.host, method=request.method, path=request.url.path, query=str(request.url.query), req_headers=hdr, req_body=body,
            status=resp.status_code, resp_bytes=len(data), resp_preview=data[:600].decode(errors="replace"), latency_ms=round((time.perf_counter() - t0) * 1000, 1), note=note)
    return Response(data, status_code=resp.status_code, headers={k: v for k, v in resp.headers.items() if k.lower() != "content-length"}, media_type=resp.media_type)


def recs(items, req: Request):
    n = int(req.query_params.get("max_records", len(items)))
    items = items[:n]
    return {"records": items, "num_records": len(items), "_links": {"self": {"href": str(req.url.path) + ("?" + req.url.query if req.url.query else "")}}}


@app.get("/api/cluster")
def cluster():
    return {"name": CLUSTER, "uuid": U(CLUSTER), "location": "Lab Rack C", "version": {"full": "NetApp Release 9.12.1P4: Fri Jun 02 2023", "generation": 9, "major": 12, "minor": 1},
            "management_interfaces": [{"name": "cluster_mgmt", "ip": {"address": "192.168.50.10"}}], "health": "ok" if not any(node_state(n) == "down" for n in NODES) else "degraded"}


@app.get("/api/cluster/nodes")
def nodes(request: Request):
    return recs([{"uuid": U(n), "name": n, "state": node_state(n), "uptime": int(3_542_000 + time.time() - T0) if node_state(n) == "up" else 0, "model": "AFF-A400",
                  "serial_number": "9000" + str(i) * 6, "version": {"full": "NetApp Release 9.12.1P4"}, "ha": {"enabled": True, "partners": [{"name": NODES[1 - i]}],
                  "giveback": {"state": "nothing_to_giveback" if node_state(n) == "up" else "failed"}},
                  "controller": {"over_temperature": "over" if lab.fault("overtemp", n) else "normal"}} for i, n in enumerate(NODES)], request)


@app.get("/api/storage/aggregates")
def aggrs(request: Request): return recs([aggr_rec(a) for a in AGGRS], request)


@app.get("/api/storage/volumes")
def vols(request: Request):
    f = request.query_params.get("fields", "")
    return recs([vol_rec(v, "metrics" in f or f == "*", "statistics" in f or f == "*") for v in VOLS], request)


@app.get("/api/storage/volumes/{vid}")
def vol(vid: str, request: Request):
    for v in VOLS:
        if U(v) == vid: return vol_rec(v, True, True)
    return JSONResponse({"error": {"message": "entry doesn't exist", "code": "4", "target": "uuid"}}, 404)


@app.get("/api/storage/aggregates/{aid}")
def aggr(aid: str):
    for a in AGGRS:
        if U(a) == aid: return aggr_rec(a)
    return JSONResponse({"error": {"message": "entry doesn't exist", "code": "4", "target": "uuid"}}, 404)


def _ctr(name, val): return {"name": name, "value": int(val)}


def counter_rows(table):
    """ONTAP counter-manager rows (cumulative raw counters, like real ONTAP)."""
    e = time.time() - T0 + 1_000_000
    rows = []
    if table.startswith("volume"):
        for v in VOLS:
            k = 1800 if vol_state(v) == "online" else 0
            ops = int(e * k)
            rows.append({"id": f"{VOLS[v][0]}:{v}", "properties": [
                _ctr("total_ops", ops), _ctr("read_ops", ops * .7), _ctr("write_ops", ops * .3), _ctr("other_ops", e * 3),
                _ctr("read_data", ops * .7 * 8192), _ctr("write_data", ops * .3 * 4096), _ctr("other_data", 0),
                _ctr("read_latency", ops * .7 * 400), _ctr("write_latency", ops * .3 * 560), _ctr("other_latency", e * 600),
                _ctr("total_data", ops * 6963), _ctr("avg_latency", ops * 440),
                {"name": "node.name", "value": NODES[0 if VOLS[v][1].endswith("n1") else 1]}]})
    else:
        for n in NODES:
            ops = int(e * 2500)
            rows.append({"id": n, "properties": [_ctr("total_ops", ops), _ctr("read_ops", ops * .6), _ctr("write_ops", ops * .4),
                                                 _ctr("read_data", ops * .6 * 8192), _ctr("write_data", ops * .4 * 4096),
                                                 _ctr("cpu_busy", e * 350000), _ctr("cpu_elapsed_time", e * 1000000),
                                                 {"name": "node.name", "value": n}]})
    return rows


@app.get("/api/cluster/counter/tables")
def counter_tables(request: Request):
    return recs([{"name": t, "description": f"{t} counters", "_links": {"self": {"href": f"/api/cluster/counter/tables/{t}"}}}
                 for t in ("volume", "volume:node", "system:node", "disk", "lun")], request)


@app.get("/api/cluster/counter/tables/{table}")
def counter_table(table: str):
    return {"name": table, "description": f"{table} counters", "counter_schemas": [], "_links": {"self": {"href": f"/api/cluster/counter/tables/{table}"}}}


@app.get("/api/cluster/counter/tables/{table}/rows")
def counter_rows_ep(table: str, request: Request):
    return recs(counter_rows(table), request)


@app.get("/api/cluster/counter/tables/{table}/rows/{rid}")
def counter_row(table: str, rid: str):
    for r in counter_rows(table):
        if r["id"] == rid: return r
    return JSONResponse({"error": {"message": "entry doesn't exist", "code": "4", "target": "id"}}, 404)


@app.get("/api/storage/disks")
def disks(request: Request): return recs([disk_rec(d) for d in DISKS], request)


@app.get("/api/network/ethernet/ports")
def eports(request: Request): return recs(ports(), request)


@app.get("/api/network/ip/interfaces")
def lifs(request: Request):
    return recs([{"name": f"lif_{s}_{i}", "uuid": U(f"lif{s}{i}"), "svm": {"name": s}, "ip": {"address": f"192.168.50.{20 + k}"}, "state": "up", "enabled": True,
                  "location": {"home_node": {"name": NODES[k % 2]}, "node": {"name": NODES[k % 2]}, "is_home": True}} for k, (s, i) in enumerate((("svm_nfs", 1), ("svm_nfs", 2), ("svm_cifs", 1)))], request)


@app.get("/api/svm/svms")
def svms(request: Request): return recs([{"name": s, "uuid": U(s), "state": "running", "subtype": "default"} for s in ("svm_nfs", "svm_cifs")], request)


@app.get("/api/snapmirror/relationships")
def sm(request: Request): return recs(snapmirror(), request)


@app.get("/api/storage/luns")
def luns(request: Request):
    off = bool(lab.fault("volume_offline", "vol_vmware_ds1"))
    node = NODES[0]
    r = {"name": "/vol/vol_vmware_ds1/lun0", "uuid": U("lun0"), "svm": {"name": "svm_nfs", "uuid": U("svm_nfs")}, "class": "regular",
         "os_type": "vmware", "serial_number": "wSAbc+Lab0001", "enabled": not off, "comment": "lab vmware datastore lun",
         "create_time": "2025-03-14T09:12:44+00:00",
         "location": {"logical_unit": "lun0", "node": {"name": node, "uuid": U(node)}, "volume": {"name": "vol_vmware_ds1", "uuid": U("vol_vmware_ds1")}},
         "status": {"state": "offline" if off else "online", "mapped": True, "container_state": "online", "read_only": False},
         "space": {"size": 2 * TB, "used": int(1.2 * TB), "guarantee": {"requested": False, "reserved": False}},
         "lun_maps": [{"igroup": {"name": "ig_esx", "uuid": U("ig_esx")}, "logical_unit_number": 0}],
         "statistics": raw("vol_vmware_ds1", 0 if off else 900)}
    return recs([r], request)


@app.get("/api/support/ems/events")
def emsev(request: Request): return recs(list(reversed(ems))[:int(request.query_params.get("max_records", 100))], request)


# ---------------------------------------------------------------- ZAPI (ONTAPI): POST /servlets/netapp.servlets.admin.XMLrequest_filer
NS = "http://www.netapp.com/filer/admin"


def zx(tag, text=None, **kids):
    e = ET.Element(tag)
    if text is not None: e.text = str(text)
    return e


def sub(parent, tag, text=None):
    e = ET.SubElement(parent, tag)
    if text is not None: e.text = str(text)
    return e


@app.post("/servlets/netapp.servlets.admin.XMLrequest_filer")
async def zapi(request: Request):
    try:
        req = ET.fromstring((await request.body()).decode())
        call = [c for c in req][0].tag.replace("{%s}" % NS, "")
    except Exception:
        return Response('<netapp version="1.0"><results status="failed" errno="13001" reason="Unable to parse request"/></netapp>', media_type="text/xml")
    root = ET.Element("netapp", version="1.31", xmlns=NS)
    res = sub(root, "results", None); res.set("status", "passed")
    if call == "system-get-ontapi-version":
        sub(res, "major-version", 1); sub(res, "minor-version", 191)
    elif call == "system-get-version":
        sub(res, "version", "NetApp Release 9.12.1P4"); sub(res, "is-clustered", "true")
    elif call == "cluster-identity-get":
        a = sub(sub(res, "attributes"), "cluster-identity-info"); sub(a, "cluster-name", CLUSTER); sub(a, "cluster-uuid", U(CLUSTER))
    elif call == "system-node-get-iter":
        al = sub(res, "attributes-list")
        for n in NODES:
            d = sub(al, "node-details-info"); sub(d, "node", n); sub(d, "is-node-healthy", "true" if node_state(n) == "up" else "false")
            sub(d, "node-uptime", int(3_542_000 + time.time() - T0) if node_state(n) == "up" else 0); sub(d, "node-model", "AFF-A400")
        sub(res, "num-records", len(NODES))
    elif call == "aggr-get-iter":
        al = sub(res, "attributes-list")
        for a in AGGRS:
            used, size = aggr_used(a), AGGRS[a][1]
            e = sub(al, "aggr-attributes"); sub(e, "aggregate-name", a)
            s = sub(e, "aggr-space-attributes"); sub(s, "size-total", int(size)); sub(s, "size-used", int(used)); sub(s, "size-available", int(size - used)); sub(s, "percent-used-capacity", int(used * 100 / size))
            r = sub(e, "aggr-raid-attributes"); sub(r, "state", "online" if node_state(AGGRS[a][0]) == "up" else "offline")
            o = sub(e, "aggr-ownership-attributes"); sub(o, "owner-name", AGGRS[a][0])
        sub(res, "num-records", len(AGGRS))
    elif call == "volume-get-iter":
        al = sub(res, "attributes-list")
        for v in VOLS:
            svm, ag, size, _, _ = VOLS[v]; used = vol_used(v)
            e = sub(al, "volume-attributes"); i = sub(e, "volume-id-attributes"); sub(i, "name", v); sub(i, "owning-vserver-name", svm); sub(i, "containing-aggregate-name", ag)
            s = sub(e, "volume-space-attributes"); sub(s, "size-total", int(size)); sub(s, "size-used", int(used)); sub(s, "size-available", int(size - used)); sub(s, "percentage-size-used", int(used * 100 / size))
            st = sub(e, "volume-state-attributes"); sub(st, "state", vol_state(v))
        sub(res, "num-records", len(VOLS))
    else:
        lab.log("unimplemented_zapi", call=call, hint="client asked for a ZAPI call the simulator does not implement yet")
        res.set("status", "failed"); res.set("errno", "13001"); res.set("reason", f"Unable to find API: {call}")
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode"), media_type="text/xml")


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE"])
def unimplemented(rest: str, request: Request):
    """Discovery mode: anything a client asks for that is not modelled yet is logged as unimplemented_endpoint."""
    lab.log("unimplemented_endpoint", path="/api/" + rest, query=str(request.url.query), method=request.method,
            hint="client asked for a REST endpoint the simulator does not implement yet")
    if rest.startswith("security/"):
        return recs([], request)          # permission/role probes: answer 'nothing special' instead of failing the sensor
    return JSONResponse({"error": {"message": f"API not found: /api/{rest}", "code": "3", "target": "uri"}}, 404)


async def main():
    cfgs = [uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("HTTP_PORT", "8080")), log_level="warning")]
    if os.path.exists(os.getenv("TLS_CERT", "/srv/cert.pem")):
        cfgs.append(uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("HTTPS_PORT", "443")), ssl_keyfile=os.getenv("TLS_KEY", "/srv/key.pem"),
                                   ssl_certfile=os.getenv("TLS_CERT", "/srv/cert.pem"), log_level="warning"))
    lab.log("started", ports=[c.port for c in cfgs])
    await asyncio.gather(*[uvicorn.Server(c).serve() for c in cfgs])


if __name__ == "__main__":
    asyncio.run(main())
