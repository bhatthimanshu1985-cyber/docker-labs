"""MQTT device simulator + tap logger. 3 devices publish telemetry with LWT; a tap client records every message seen on '#'.
Control API :9101 (/_lab/*)."""
import json, math, os, random, socket, threading, time
import paho.mqtt.client as mqtt
import uvicorn
from fastapi import FastAPI
from labcommon import Lab

lab = Lab("mqtt")
HOST, PORT = os.getenv("MQTT_HOST", "mosquitto"), int(os.getenv("MQTT_PORT", "1883"))
USER, PASS = os.getenv("MQTT_USER", "lab"), os.getenv("MQTT_PASS", "labpass")
T0 = time.time()
w = lambda base, amp, per: round(base + amp * math.sin((time.time() - T0) / per) + random.uniform(-.1, .1), 2)

# device id -> (interval s, qos, [(topic, value-fn)])
js = lambda **kw: json.dumps({**kw, "ts": int(time.time())})
DEVICES = {
    "plc-01": (5, 1, [("factory/line1/temperature", lambda: js(value=w(60, 8, 60), unit="C")), ("factory/line1/pressure", lambda: js(value=w(4.2, .4, 25), unit="bar")),
                      ("factory/line1/motor", lambda: js(state="RUNNING", rpm=1450)),
                      ("factory/line1/plc-01", lambda: js(temperature=w(60, 8, 60), pressure=w(4.2, .4, 25), rpm=1450, counter=int(time.time() - T0)))]),
    "sensor-02": (10, 0, [("factory/line2/humidity", lambda: js(value=w(45, 10, 120), unit="%")), ("factory/line2/battery", lambda: js(value=round(max(0, 100 - (time.time() - T0) / 3600), 1), unit="%"))]),
    "gateway-03": (15, 2, [("factory/gateway/telemetry", lambda: js(temp=w(21, 2, 300), rssi=random.randint(-80, -60), fw="1.4.2"))]),
}
clients, killed_until = {}, {}


def mk(cid, will=None):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid, protocol=mqtt.MQTTv311)
    c.username_pw_set(USER, PASS)
    if will: c.will_set(*will)
    c.reconnect_delay_set(1, 10)
    c.on_connect = lambda cl, ud, fl, rc, pr=None: lab.log("connected", client=cid, reason=str(rc), session_present=fl.session_present)
    c.on_disconnect = lambda cl, ud, fl, rc, pr=None: lab.log("disconnected", client=cid, reason=str(rc))
    return c


def device_loop(did):
    interval, qos, topics = DEVICES[did]
    c = clients[did]
    while True:
        time.sleep(max(1, interval * float(lab.fault("interval_factor") or 1)))
        if lab.fault("pause", did) or not c.is_connected():
            continue
        for topic, fn in topics:
            payload = "\xff\xfe<<corrupt>>" if lab.fault("garbage", did) else fn()
            info = c.publish(topic, payload, qos=qos, retain=(topic.endswith("motor")))
            lab.log("publish", client=did, topic=topic, qos=qos, payload=str(payload)[:120], mid=info.mid, rc=info.rc)


def tap():
    t = mk("lab-tap")
    t.on_message = lambda cl, ud, m: lab.log("tap", topic=m.topic, qos=m.qos, retain=bool(m.retain), size=len(m.payload), payload=m.payload[:150].decode("utf-8", "replace"))
    t.on_connect = lambda cl, ud, fl, rc, pr=None: (lab.log("connected", client="lab-tap", reason=str(rc)), cl.subscribe("#", 1))
    t.connect_async(HOST, PORT, 30); t.loop_start()


def action(name, target, value):
    if name == "kill_connection":   # ungraceful drop (no DISCONNECT packet) -> broker publishes the device's Last Will
        c = clients[target]; secs = int(value or 30)
        c.reconnect_delay_set(secs, secs)
        try: c._sock.shutdown(socket.SHUT_RDWR)
        except Exception as e: return f"socket kill failed: {e}"
        threading.Timer(2, lambda: c.reconnect_delay_set(1, 10)).start()
        return f"{target} dropped; stays offline ~{secs}s"
    if name == "burst":             # N rapid QoS1 messages
        n = int(value or 500)
        for i in range(n): clients[target or "plc-01"].publish("factory/burst/test", f"msg-{i}", qos=1)
        return f"published {n}"
    if name == "oversize":          # exceeds broker message_size_limit (262144) -> broker drops/disconnects
        r = clients[target or "plc-01"].publish("factory/oversize", b"x" * int(value or 300_000), qos=1)
        return f"publish rc={r.rc} mid={r.mid}"
    if name == "publish":           # publish an arbitrary payload: value = "topic|payload"
        t, p = str(value).split("|", 1); clients[target or "plc-01"].publish(t, p, qos=1, retain=False); return "ok"
    return "unknown action (kill_connection, burst, oversize, publish)"


app = FastAPI(title="mqtt-sim")
lab.attach(app, lambda: {"devices": {d: ("connected" if c.is_connected() else "DISCONNECTED") for d, c in clients.items()}, "broker": f"{HOST}:{PORT}"}, on_action=action)

if __name__ == "__main__":
    for did, (interval, qos, topics) in DEVICES.items():
        will = (f"factory/{did}/status", "offline", 1, True)
        c = mk(did, will); clients[did] = c
        c.on_connect = (lambda d: lambda cl, ud, fl, rc, pr=None: (lab.log("connected", client=d, reason=str(rc), session_present=fl.session_present), cl.publish(f"factory/{d}/status", "online", qos=1, retain=True)))(did)
        c.connect_async(HOST, PORT, 30); c.loop_start()
        threading.Thread(target=device_loop, args=(did,), daemon=True).start()
    tap()
    lab.log("started", broker=f"{HOST}:{PORT}", devices=list(DEVICES))
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("CONTROL_PORT", "9101")), log_level="warning")
