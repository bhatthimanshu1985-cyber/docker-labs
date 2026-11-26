"""netlab simulation core, shared by the SNMP simulator and the REST mock.

Everything the simulated devices report is a *pure function of (device, time)* plus a seeded hash, so the SNMP
container and the REST container agree on CPU, memory, link state, VPN state, outages ... without talking to
each other.  Counters are integrated from a fixed boot time in 5 s steps (state kept per process).

Behaviour is driven by scenarios.json (hot-reloaded every ~2 s):  daily traffic curves, noise, bursts, error
counters, link flaps, scheduled outages, reboots, packet loss, latency.  See README for the schema.
"""
import copy, datetime as dt, hashlib, json, math, os, time
from zoneinfo import ZoneInfo

CFG_PATH = os.getenv("SCENARIO_FILE", "/srv/scenarios/scenarios.json")
STEP = 5.0                      # counter integration step (s)
C32, C64 = 2 ** 32, 2 ** 64


# ------------------------------------------------------------------ deterministic randomness
def _h(*parts):
    d = hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest()
    return int.from_bytes(d, "big") / 2 ** 64          # [0,1)


def vnoise(key, t, period):
    """smooth value noise in [-1,1]"""
    x = t / period
    i = math.floor(x)
    f = x - i
    f = f * f * (3 - 2 * f)
    a, b = _h(key, i) * 2 - 1, _h(key, i + 1) * 2 - 1
    return a + (b - a) * f


def smooth(a, b, x):
    if x <= a: return 0.0
    if x >= b: return 1.0
    x = (x - a) / (b - a)
    return x * x * (3 - 2 * x)


def deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


# ------------------------------------------------------------------ config (hot reload, named scenarios)
class Config:
    def __init__(self, path):
        self.path, self.mtime, self.checked, self.eff, self.raw = path, -1, 0, {"devices": {}}, {}

    def get(self):
        now = time.time()
        if now - self.checked > 2:
            self.checked = now
            try:
                m = os.path.getmtime(self.path)
                if m != self.mtime:
                    with open(self.path) as f:
                        raw = json.load(f)
                    eff = raw
                    for name in raw.get("active_scenarios", []):
                        patch = raw.get("scenarios", {}).get(name, {})
                        eff = deep_merge(eff, patch)
                    self.raw, self.eff, self.mtime = raw, eff, m
            except (OSError, ValueError):
                pass            # keep last good config
        return self.eff


def parse_ts(s, tz):
    return dt.datetime.fromisoformat(s).replace(tzinfo=tz).timestamp()


# ------------------------------------------------------------------ daily curves
def diurnal(profile, d):
    h, wd = d.hour + d.minute / 60 + d.second / 3600, d.weekday()
    work = smooth(7, 9.5, h) - smooth(17, 19, h)
    lunch = 0.22 * math.exp(-((h - 12.5) / 0.7) ** 2)
    office = max(0.0, work - lunch)
    if profile == "office":
        return 0.06 + 0.94 * office if wd < 5 else 0.05 + 0.10 * office
    if profile == "wan":                                    # internet edge: office + evening streaming
        eve = smooth(18, 20, h) - smooth(23, 24, h)
        f = 0.12 + 0.55 * office + 0.33 * max(0, eve)
        return f if wd < 5 else 0.15 + 0.2 * office + 0.65 * max(0, eve)
    if profile == "server":                                 # steady + night backup window
        bk = math.exp(-((h - 2.5) / 0.6) ** 2)
        return 0.45 + 0.25 * office + 0.55 * bk
    if profile == "idle":
        return 0.03
    if profile == "bursty":
        return 0.2 + 0.2 * office
    return 1.0                                              # "flat"


def window_hit(key, t, bucket_s, p, dur_range):
    """deterministic random events: per bucket probability p, random start+duration.
    returns (active, start, end) of the event covering t (looking back 2 buckets), else (False, None, None)"""
    b0 = math.floor(t / bucket_s)
    for b in (b0, b0 - 1, b0 - 2):
        if _h(key, "e", b) < p:
            st = b * bucket_s + _h(key, "s", b) * bucket_s
            du = dur_range[0] + _h(key, "d", b) * (dur_range[1] - dur_range[0])
            if st <= t < st + du:
                return True, st, st + du
    return False, None, None


def last_window_end(key, t, bucket_s, p, dur_range, back=12):
    b0 = math.floor(t / bucket_s)
    best = None
    for b in range(b0, b0 - back, -1):
        if _h(key, "e", b) < p:
            st = b * bucket_s + _h(key, "s", b) * bucket_s
            en = st + dur_range[0] + _h(key, "d", b) * (dur_range[1] - dur_range[0])
            if st <= t:
                best = max(best or 0, st if t < en else en)
                break
    return best


# ------------------------------------------------------------------ the simulator
class Sim:
    def __init__(self, path=CFG_PATH):
        self.cfg = Config(path)
        self.state = {}
        self._rb_cache = {}

    # ---- config helpers
    def conf(self):
        return self.cfg.get()

    def dev(self, name):
        return self.conf().get("devices", {}).get(name, {})

    def tz(self):
        return ZoneInfo(self.conf().get("timezone", "Europe/Berlin"))

    def local(self, t):
        return dt.datetime.fromtimestamp(t, self.tz())

    def seed(self):
        return self.conf().get("seed", 1)

    def _sched_hit(self, items, t):
        """items: [{"at":"22:10","duration_s":600,"days":"daily"|[0..6]}]  -> (active, start)"""
        d = self.local(t)
        for it in items or []:
            hh, mm = [int(x) for x in it["at"].split(":")]
            for back in (0, 1):
                day = d - dt.timedelta(days=back)
                days = it.get("days", "daily")
                if days != "daily" and day.weekday() not in days:
                    continue
                st = day.replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp()
                if st <= t < st + it.get("duration_s", 300):
                    return True, st, st + it.get("duration_s", 300)
        return False, None, None

    def _random_reboots(self, dev, mtbf_days, t):
        """hourly buckets, probability 1/(mtbf*24); cached per (device, mtbf, day)"""
        day0 = math.floor(t / 86400)
        key = (dev, mtbf_days, self.seed(), day0)
        hit = self._rb_cache.get(key)
        if hit is None:
            hit = []
            for hb in range((day0 - 120) * 24, (day0 + 1) * 24 + 24):
                if _h(self.seed(), dev, "reboot", hb) < 1.0 / (mtbf_days * 24):
                    hit.append(hb * 3600 + _h(self.seed(), dev, "rbt", hb) * 3600)
            self._rb_cache = {k: v for k, v in self._rb_cache.items() if k[3] >= day0 - 1}
            self._rb_cache[key] = hit
        return hit

    # ---- boot / reboot / reachability
    def boot_info(self, dev, t):
        """returns (boot_time, unreachable_now)"""
        c = self.dev(dev)
        tz = self.tz()
        boot = parse_ts(c.get("boot", "2026-09-01T03:00:00"), tz)
        down_s = c.get("reboot_downtime_s", 120)
        unreachable = False
        events = [parse_ts(x, tz) for x in c.get("reboots", [])]
        mtbf = c.get("reboot_mtbf_days", 0)
        if mtbf:
            events += self._random_reboots(dev, mtbf, t)
        for ev in events:
            if ev <= t:
                if t < ev + down_s:
                    unreachable = True
                boot = max(boot, ev + down_s)
        return boot, unreachable

    def net(self, dev, t=None):
        """network behaviour towards the poller: dict(down, loss_pct, latency)"""
        t = t or time.time()
        c = self.dev(dev)
        n = c.get("network", {})
        _, unreachable = self.boot_info(dev, t)
        out_active, _, _ = self._sched_hit(n.get("outages"), t)
        rnd = window_hit((self.seed(), dev, "netoutage"), t, 3600, n.get("random_outages_per_day", 0) / 24.0, (60, 600))[0]
        return {"down": unreachable or out_active or rnd, "loss_pct": n.get("loss_pct", 0),
                "latency_ms": n.get("latency_ms", [2, 15]), "rate_limit_per_s": n.get("rate_limit_per_s", 0)}

    def uptime_ticks(self, dev, t=None):
        t = t or time.time()
        boot, _ = self.boot_info(dev, t)
        return int(max(0, t - boot) * 100) % C32

    # ---- gauges
    def load(self, dev, t):
        c = self.dev(dev)
        return diurnal(c.get("load_profile", "office"), self.local(t))

    def _spike(self, dev, key, t, per_hour, amp, bucket=300):
        if not per_hour: return 0.0
        b = math.floor(t / bucket)
        if _h(self.seed(), dev, key, "sp", b) < per_hour * bucket / 3600:
            frac = (t % bucket) / bucket
            return amp * (0.4 + 0.6 * _h(self.seed(), dev, key, "sa", b)) * math.sin(math.pi * frac) ** 2
        return 0.0

    def cpu(self, dev, t=None):
        t = t or time.time()
        c = self.dev(dev).get("cpu", {})
        v = (c.get("base", 12) + c.get("load_amp", 8) * self.load(dev, t)
             + c.get("noise", 2) * vnoise((self.seed(), dev, "cpu"), t, 20)
             + 0.6 * c.get("noise", 2) * vnoise((self.seed(), dev, "cpu2"), t, 4)
             + self._spike(dev, "cpu", t, c.get("spike_per_hour", 1), c.get("spike_amp", 25)))
        return max(0.5, min(100.0, v))

    def cpu_avg(self, dev, t, window):
        n = 6
        return sum(self.cpu(dev, t - window * i / n) for i in range(n)) / n

    def cpu_cores(self, dev, t, n=4):
        base = self.cpu(dev, t)
        return [max(0.0, min(100.0, base * (0.7 + 0.6 * _h(self.seed(), dev, "core", i)) + 5 * vnoise((dev, "c", i), t, 7))) for i in range(n)]

    def mem(self, dev, t=None):
        t = t or time.time()
        c = self.dev(dev).get("mem", {})
        boot, _ = self.boot_info(dev, t)
        days = max(0.0, (t - boot) / 86400)
        reset = c.get("leak_reset_days", 0)
        if reset: days %= reset
        v = (c.get("base", 40) + c.get("load_amp", 4) * self.load(dev, t) + c.get("drift_per_day", 0.3) * days
             + c.get("noise", 0.6) * vnoise((self.seed(), dev, "mem"), t, 90))
        return max(1.0, min(99.5, v))

    def temp(self, dev, t=None):
        t = t or time.time()
        c = self.dev(dev).get("temp", {})
        cpu_base = self.dev(dev).get("cpu", {}).get("base", 12)
        return (c.get("base", 38) + c.get("cpu_coupling", 0.1) * (self.cpu(dev, t) - cpu_base)
                + 1.2 * math.sin((self.local(t).hour + self.local(t).minute / 60 - 15) / 24 * 2 * math.pi)
                + 0.5 * vnoise((self.seed(), dev, "temp"), t, 300))

    def sessions(self, dev, t=None):
        t = t or time.time()
        c = self.dev(dev).get("sessions", {})
        mbps = self._wan_mbps(dev, t)
        v = c.get("base", 800) * (0.4 + 0.6 * self.load(dev, t)) + c.get("per_mbps", 30) * mbps \
            + c.get("noise", 60) * vnoise((self.seed(), dev, "ses"), t, 15) \
            + self._spike(dev, "ses", t, c.get("spike_per_hour", 0.5), c.get("spike_amp", 3000))
        return int(max(0, v))

    def session_rate(self, dev, t=None):
        t = t or time.time()
        return int(max(0, 0.04 * self.sessions(dev, t) + 12 * vnoise((self.seed(), dev, "sesrate"), t, 6) + 15))

    def _wan_mbps(self, dev, t):
        for name, ic in self.dev(dev).get("interfaces", {}).items():
            if ic.get("role") == "wan" or ic.get("profile") == "wan":
                return (self._rate(dev, name, t, "in") + self._rate(dev, name, t, "out")) * 8 / 1e6
        return 0.0

    # ---- interfaces
    def iface_cfg(self, dev, name):
        return self.dev(dev).get("interfaces", {}).get(name, {})

    def _rate(self, dev, name, t, direction):
        """bytes/s for in|out"""
        ic = self.iface_cfg(dev, name)
        base = ic.get(direction + "_bps", 0)
        if not base: return 0.0
        key = (self.seed(), dev, name, direction)
        f = diurnal(ic.get("profile", "office"), self.local(t))
        f *= 1 + 0.22 * vnoise(key, t, 30) + 0.08 * vnoise((key, "fast"), t, 4)
        # bursts: per-minute probability, short, sinusoidal envelope
        bpm = ic.get("bursts_per_hour", 6) / 60.0
        b = math.floor(t / 60)
        if _h(key, "b", b) < bpm:
            frac = (t % 60) / 60
            f *= 1 + (1 + 5 * _h(key, "ba", b)) * math.sin(math.pi * frac) ** 2
        # scenario multiplier (e.g. DDoS window)
        for w in ic.get("surges", []):
            on, st, en = self._sched_hit([w], t)
            if on:
                f *= w.get("factor", 5) * min(1, (t - st) / 30, (en - t) / 30 + 0.2)
        r = base * max(0.0, f)
        speed = ic.get("speed", 1_000_000_000) / 8
        return min(r, speed * 0.97) if speed else r

    def link_up(self, dev, name, t=None):
        """(oper_up, last_change_time)"""
        t = t or time.time()
        ic = self.iface_cfg(dev, name)
        boot, unreachable = self.boot_info(dev, t)
        if ic.get("status") == "down":
            return False, boot
        on, st, _ = self._sched_hit(ic.get("outages"), t)
        if on:
            return False, st
        fpd = ic.get("flaps_per_day", 0)
        if fpd:
            key = (self.seed(), dev, name, "flap")
            on, st, _ = window_hit(key, t, 900, fpd / 96.0, tuple(ic.get("flap_s", [15, 120])))
            if on:
                return False, st
            lw = last_window_end(key, t, 900, fpd / 96.0, tuple(ic.get("flap_s", [15, 120])))
            return True, max(boot, lw or boot)
        return True, boot

    def iface(self, dev, name, t=None):
        """advance + return counters/state for one interface"""
        t = t or time.time()
        ic = self.iface_cfg(dev, name)
        boot, _ = self.boot_info(dev, t)
        up, lchg = self.link_up(dev, name, t)
        st = self.state.setdefault((dev, name), None)
        if st is None or st["boot"] != boot:
            # counters start where a device that has been up since `boot` would be: average rate * elapsed (bounded)
            el = max(0.0, min(t - boot, 400 * 86400))
            seed = lambda k: _h(self.seed(), dev, name, "init", k)
            avg_in, avg_out = ic.get("in_bps", 0) * 0.35, ic.get("out_bps", 0) * 0.35
            st = {"boot": boot, "t": t, "in": avg_in * el, "out": avg_out * el, "inerr": 0.0, "outerr": 0.0,
                  "indisc": 0.0, "outdisc": 0.0, "inmc": avg_in * el * 0.002 / 90, "outmc": avg_out * el * 0.0005 / 90}
            if ic.get("in_bps", 0) == 0: st["in"] = st["out"] = 0.0
            self.state[(dev, name)] = st
        # integrate
        tt, n = st["t"], 0
        if t - tt > 7200: tt = t - 7200
        while tt < t - 1e-6 and n < 1500:
            step = min(STEP * (1 + (t - tt) // 3600), t - tt)
            mid = tt + step / 2
            upm, _ = self.link_up(dev, name, mid) if step > 0 else (up, 0)
            if upm:
                ri, ro = self._rate(dev, name, mid, "in"), self._rate(dev, name, mid, "out")
                st["in"] += ri * step; st["out"] += ro * step
                st["inmc"] += ri * step * 0.002 / 90; st["outmc"] += ro * step * 0.0005 / 90
                epk = ic.get("errors_per_hour", 0.3)
                eb = int(mid // 20)
                if epk and eb != st.get("eb") and _h(self.seed(), dev, name, "err", eb) < epk * 20 / 3600:
                    st["inerr"] += 1 + int(8 * _h(self.seed(), dev, name, "errn", eb))
                    if _h(self.seed(), dev, name, "errd", eb) < 0.4: st["outerr"] += 1
                st["eb"] = eb
                util = max(ri, ro) * 8 / max(ic.get("speed", 1e9), 1)
                db = int(mid // 30)
                dph = ic.get("discards_per_hour", 0.1)
                if db != st.get("db") and (util > 0.85 or (dph and _h(self.seed(), dev, name, "dis", db) < dph * 30 / 3600)):
                    st["outdisc"] += 1 + int(30 * max(0, util - 0.8)); st["indisc"] += int(10 * max(0, util - 0.85))
                st["db"] = db
            tt += step; n += 1
        st["t"] = t
        pk = ic.get("avg_pkt", 780)
        pk_in = pk * (1 + 0.25 * vnoise((dev, name, "pk"), t, 600))
        return {"up": up, "last_change_ticks": int(max(0, t - lchg) * 100) % C32,
                "in_oct": int(st["in"]), "out_oct": int(st["out"]),
                "in_uc": int(st["in"] / pk_in * 0.985), "out_uc": int(st["out"] / pk * 0.985),
                "in_mc": int(st["inmc"]), "out_mc": int(st["outmc"]),
                "in_err": int(st["inerr"]), "out_err": int(st["outerr"]),
                "in_disc": int(st["indisc"]), "out_disc": int(st["outdisc"]),
                "in_bps": self._rate(dev, name, t, "in") * 8 if up else 0, "out_bps": self._rate(dev, name, t, "out") * 8 if up else 0}

    # ---- VPN
    def vpn(self, dev, name, t=None):
        t = t or time.time()
        c = self.dev(dev).get("vpn", {}).get(name, {})
        up = c.get("state", "up") == "up"
        if up and c.get("flaps_per_day"):
            up = not window_hit((self.seed(), dev, name, "vpn"), t, 900, c["flaps_per_day"] / 96.0, tuple(c.get("flap_s", [30, 300])))[0]
        on, _, _ = self._sched_hit(c.get("outages"), t)
        if on: up = False
        boot, _ = self.boot_info(dev, t)
        st = self.state.setdefault((dev, "vpn", name), {"t": t, "in": 0.0, "out": 0.0, "up": up})
        if st["up"] and up and t > st["t"]:
            f = 0.2 + 0.8 * self.load(dev, t)
            st["in"] += c.get("in_bps", 90_000) * f * (t - st["t"]) * (1 + 0.3 * vnoise((dev, name, "vi"), t, 25))
            st["out"] += c.get("out_bps", 70_000) * f * (t - st["t"]) * (1 + 0.3 * vnoise((dev, name, "vo"), t, 25))
        if not up and st["up"]:
            st["in"] = st["out"] = 0.0              # tunnel counters reset on re-key
        st["t"], st["up"] = t, up
        return {"up": up, "in": int(st["in"]), "out": int(st["out"]), "remote": c.get("remote", "192.0.2.10")}

    def ssl_users(self, dev, t=None):
        t = t or time.time()
        c = self.dev(dev).get("ssl_vpn", {})
        return int(max(0, c.get("users_max", 6) * self.load(dev, t) * (0.6 + 0.4 * (vnoise((dev, "sslu"), t, 300) + 1) / 2)))

    # ---- SNMP record evaluation (used by the snmpsim variation module)
    def snmp_value(self, s, t=None):
        t = t or time.time()
        dev, k = s["d"], s["k"]
        if k == "ifc":
            v = self.iface(dev, s["i"], t)[s["f"]]
            return v % (C64 if s.get("w") == "64" else C32)
        if k == "ifs":
            v = self.iface(dev, s["i"], t)
            return {"oper": 1 if v["up"] else 2, "last": v["last_change_ticks"]}[s["f"]]
        if k == "uptime":
            return self.uptime_ticks(dev, t)
        if k == "g":
            f = s["f"]
            if f == "cpu": return int(round(self.cpu(dev, t)))
            if f == "cpu1": return int(round(self.cpu_avg(dev, t, 60)))
            if f == "cpu5": return int(round(self.cpu_avg(dev, t, 300)))
            if f == "cpu5s": return int(round(self.cpu(dev, t)))
            if f == "mem": return int(round(self.mem(dev, t)))
            if f == "mem_used": return int(self.mem(dev, t) / 100 * float(s.get("total", 4e9)))
            if f == "mem_free": return int((1 - self.mem(dev, t) / 100) * float(s.get("total", 4e9)))
            if f == "temp": return int(round(self.temp(dev, t)))
            if f == "ses": return self.sessions(dev, t)
            if f == "sesrate": return self.session_rate(dev, t)
            if f == "disk": return int(float(s.get("total", 120000)) * (0.26 + 0.0003 * max(0, (t - parse_ts(self.dev(dev).get("boot", "2026-09-01T03:00:00"), self.tz())) / 86400)))
            if f == "core": return int(round(self.cpu_cores(dev, t)[int(s["n"])]))
            if f == "sslusers": return self.ssl_users(dev, t)
            if f == "fan": return 1
        if k == "vpn":
            v = self.vpn(dev, s["n"], t)
            return {"status": 2 if v["up"] else 1, "in": v["in"] % C32, "out": v["out"] % C32}[s["f"]]
        raise KeyError(s)


SIM = Sim()
