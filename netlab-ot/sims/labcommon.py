"""Shared helpers: JSONL debug logging + fault/action control API (/_lab/*) used by every simulator."""
import collections, json, os, threading
from datetime import datetime, timezone
from fastapi import Body, FastAPI

LOG_DIR = os.getenv("LOG_DIR", "/logs")
MAX_LOG_BYTES = 50 * 1024 * 1024


class Lab:
    def __init__(self, name):
        self.name = name
        self.faults = {}            # key "name" or "name:target" -> value
        self.ring = collections.deque(maxlen=5000)
        self.lock = threading.Lock()
        os.makedirs(LOG_DIR, exist_ok=True)
        self.path = os.path.join(LOG_DIR, f"{name}.jsonl")

    # ---- logging ---------------------------------------------------------
    def log(self, event, **kw):
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "sim": self.name, "event": event, **kw}
        if self.faults:
            rec["active_faults"] = dict(self.faults)
        line = json.dumps(rec, default=str)
        with self.lock:
            self.ring.append(rec)
            try:
                if os.path.exists(self.path) and os.path.getsize(self.path) > MAX_LOG_BYTES:
                    os.replace(self.path, self.path + ".1")
                with open(self.path, "a") as f:
                    f.write(line + "\n")
            except OSError:
                pass
        print(line, flush=True)

    # ---- faults ----------------------------------------------------------
    def fault(self, name, target=None):
        """Value of an active fault (None if inactive). A fault set without target applies to every target."""
        if target is not None and f"{name}:{target}" in self.faults:
            return self.faults[f"{name}:{target}"]
        return self.faults.get(name)

    def attach(self, app: FastAPI, state_fn, on_fault=None, on_action=None):
        @app.get("/_lab/state")
        def state():
            return {"sim": self.name, "active_faults": self.faults, "state": state_fn()}

        @app.get("/_lab/log")
        def log(n: int = 100, event: str = ""):
            recs = [r for r in self.ring if not event or r["event"] == event]
            return recs[-min(n, 5000):]

        @app.post("/_lab/fault")
        def set_fault(body: dict = Body(...)):
            name, target, value = body["name"], body.get("target"), body.get("value", True)
            self.faults[f"{name}:{target}" if target else name] = value
            self.log("fault_set", fault=name, target=target, value=value)
            if on_fault:
                on_fault(name, target, value)
            return {"active_faults": self.faults}

        @app.delete("/_lab/fault")
        def clear(name: str = "", target: str = ""):
            key = f"{name}:{target}" if target else name
            keys = [k for k in self.faults if not name or k == key or k.startswith(name + ":") and not target]
            for k in keys:
                self.faults.pop(k, None)
            self.log("fault_cleared", cleared=keys or "none")
            return {"active_faults": self.faults}

        @app.post("/_lab/action")
        def action(body: dict = Body(...)):
            if not on_action:
                return {"error": "no actions for this simulator"}
            self.log("action", action=body["name"], target=body.get("target"), value=body.get("value"))
            return {"result": on_action(body["name"], body.get("target"), body.get("value"))}
