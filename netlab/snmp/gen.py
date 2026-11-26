"""Generates snmpsim .snmprec files from scenarios.json.  One file per device, community string = file name.
Static OIDs are plain records; dynamic ones are tagged ':sim' and evaluated at query time by variation/sim.py
(which asks simcore.SIM for the value).  Record value format for ':sim':  k=<kind>,d=<device>,i=<ifname>,f=<field>..."""
import json, os, sys

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "data"
os.makedirs(OUT, exist_ok=True)
C32 = 4294967295
cfg = json.load(open(SRC))


class Dev:
    def __init__(self, name):
        self.name, self.r = name, {}
        self.c = cfg["devices"][name]

    def s(self, oid, v): self.r[oid] = ("4", v)
    def i(self, oid, v): self.r[oid] = ("2", str(v))
    def oid(self, oid, v): self.r[oid] = ("6", v)
    def g(self, oid, v): self.r[oid] = ("66", str(v))
    def ip(self, oid, v): self.r[oid] = ("64", v)
    def hexs(self, oid, v): self.r[oid] = ("4x", v)

    def dyn(self, oid, tag, k, **kw):
        spec = ",".join(f"{a}={b}" for a, b in dict(k=k, d=self.name, **kw).items())
        self.r[oid] = (f"{tag}:sim", spec)

    def system(self):
        c = self.c
        self.s("1.3.6.1.2.1.1.1.0", c["descr"])
        self.oid("1.3.6.1.2.1.1.2.0", c["objid"])
        self.dyn("1.3.6.1.2.1.1.3.0", "67", "uptime")
        self.s("1.3.6.1.2.1.1.4.0", "netops@example.lab")
        self.s("1.3.6.1.2.1.1.5.0", c["sysname"])
        self.s("1.3.6.1.2.1.1.6.0", c["location"])
        self.i("1.3.6.1.2.1.1.7.0", 78)

    def interfaces(self):
        ports = list(self.c["interfaces"].items())
        self.i("1.3.6.1.2.1.2.1.0", len(ports))
        for n, (name, p) in enumerate(ports, 1):
            t, x = f"1.3.6.1.2.1.2.2.1.%d.{n}", f"1.3.6.1.2.1.31.1.1.1.%d.{n}"
            speed = p.get("speed", 0)
            ctr = lambda oid, f, w="32", tag="65": self.dyn(oid, tag, "ifc", i=name, f=f, w=w)
            self.i(t % 1, n); self.s(t % 2, name); self.i(t % 3, p.get("type", 6)); self.i(t % 4, 1500)
            self.g(t % 5, min(speed, C32))
            self.hexs(t % 6, "00AABB%06X" % (abs(hash((self.name, name))) & 0xFFFFFF))
            self.i(t % 7, 2 if p.get("admin") == "down" else 1)
            self.dyn(t % 8, "2", "ifs", i=name, f="oper")
            self.dyn(t % 9, "67", "ifs", i=name, f="last")
            ctr(t % 10, "in_oct"); ctr(t % 11, "in_uc"); ctr(t % 13, "in_disc"); ctr(t % 14, "in_err")
            ctr(t % 16, "out_oct"); ctr(t % 17, "out_uc"); ctr(t % 19, "out_disc"); ctr(t % 20, "out_err")
            self.s(x % 1, name)
            ctr(x % 2, "in_mc"); ctr(x % 4, "out_mc")
            ctr(x % 6, "in_oct", "64", "70"); ctr(x % 7, "in_uc", "64", "70")
            ctr(x % 10, "out_oct", "64", "70"); ctr(x % 11, "out_uc", "64", "70")
            self.g(x % 15, speed // 1_000_000)
            self.s(x % 18, f"{self.c['sysname']} {name}")

    def cisco_health(self):
        b = "1.3.6.1.4.1.9.9.109.1.1.1.1"      # cpmCPUTotalTable
        self.i(f"{b}.2.1", 1001)
        self.dyn(f"{b}.6.1", "66", "g", f="cpu5s"); self.dyn(f"{b}.7.1", "66", "g", f="cpu1"); self.dyn(f"{b}.8.1", "66", "g", f="cpu5")
        m = "1.3.6.1.4.1.9.9.48.1.1.1"         # ciscoMemoryPoolTable
        self.s(f"{m}.2.1", "Processor"); self.g(f"{m}.3.1", 1)
        self.dyn(f"{m}.5.1", "66", "g", f="mem_used", total="4000000000")
        self.dyn(f"{m}.6.1", "66", "g", f="mem_free", total="4000000000")
        e = "1.3.6.1.4.1.9.9.13.1"             # CISCO-ENVMON-MIB
        self.s(f"{e}.3.1.2.1", "Chassis Temperature"); self.dyn(f"{e}.3.1.3.1", "66", "g", f="temp")
        self.g(f"{e}.3.1.4.1", 75); self.i(f"{e}.3.1.6.1", 1)
        for idx, nm in ((1, "Switch#1, Fan#1"), (2, "Switch#1, Fan#2")):
            self.s(f"{e}.4.1.2.{idx}", nm); self.i(f"{e}.4.1.3.{idx}", 1)
        for idx, nm in ((1, "Switch#1, PowerSupply#1, Normal"), (2, "Switch#1, PowerSupply#2, NotPresent")):
            self.s(f"{e}.5.1.2.{idx}", nm); self.i(f"{e}.5.1.3.{idx}", 1 if idx == 1 else 5)

    def fortigate(self):
        f = "1.3.6.1.4.1.12356.101.4.1"        # FORTINET-FORTIGATE-MIB fgSystemInfo
        self.s(f"{f}.1.0", "v7.2.5,build1517,230731 (GA.M)")
        self.dyn(f"{f}.3.0", "66", "g", f="cpu"); self.dyn(f"{f}.4.0", "66", "g", f="mem")
        self.g(f"{f}.5.0", 4_000_000)
        self.dyn(f"{f}.6.0", "66", "g", f="disk", total="120000"); self.g(f"{f}.7.0", 120_000)
        self.dyn(f"{f}.8.0", "66", "g", f="ses"); self.dyn(f"{f}.11.0", "66", "g", f="sesrate")
        self.dyn(f"{f}.12.0", "66", "g", f="sesrate")
        self.i("1.3.6.1.4.1.12356.101.13.1.1.0", 1)        # fgHaSystemMode: standalone
        p = "1.3.6.1.4.1.12356.101.4.4.2.1"                 # fgProcessorTable (per core)
        for n in range(4):
            self.i(f"{p}.1.{n + 1}", n + 1); self.dyn(f"{p}.2.{n + 1}", "66", "g", f="core", n=n)
        t = "1.3.6.1.4.1.12356.101.12.2.2.1"                # fgVpnTunTable
        for n, (name, v) in enumerate(self.c.get("vpn", {}).items(), 1):
            self.i(f"{t}.1.{n}", n); self.s(f"{t}.2.{n}", name); self.s(f"{t}.3.{n}", name)
            self.ip(f"{t}.4.{n}", v.get("remote", "192.0.2.10"))
            self.dyn(f"{t}.18.{n}", "65", "vpn", n=name, f="in"); self.dyn(f"{t}.19.{n}", "65", "vpn", n=name, f="out")
            self.dyn(f"{t}.20.{n}", "2", "vpn", n=name, f="status")      # 1=down 2=up
        s = "1.3.6.1.4.1.12356.101.12.2.3.1"                # fgVpnSslStatsTable (best effort)
        self.i(f"{s}.1.1", 1); self.dyn(f"{s}.2.1", "66", "g", f="sslusers")
        self.g(f"{s}.3.1", 4); self.dyn(f"{s}.4.1", "66", "g", f="sslusers")

    def write(self):
        key = lambda o: tuple(int(p) for p in o.split("."))
        with open(os.path.join(OUT, self.name + ".snmprec"), "w") as fh:
            for o in sorted(self.r, key=key):
                tag, val = self.r[o]
                fh.write(f"{o}|{tag}|{val}\n")


for name, c in cfg["devices"].items():
    d = Dev(name)
    d.system(); d.interfaces()
    if c["kind"] == "cisco": d.cisco_health()
    if c["kind"] == "fortigate": d.fortigate()
    d.write()
print("generated", sorted(os.listdir(OUT)))
