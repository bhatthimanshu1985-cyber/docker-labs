"""Generates snmpsim .snmprec files. Community string = file name (cisco-router, cisco-switch, fortigate, switch)."""
import os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "data"
os.makedirs(OUT, exist_ok=True)
C32 = 4294967295


def gauge(base, amp, rate, lo=0, hi=100):
    return f"function=sin,rate={rate},scale={amp},offset={base},min={lo},max={hi}"


def counter(bps, init=0, mx=C32):
    return f"function=fabs%0,cumulative=1,rate=1,offset={bps},initial={init},min=0,max={mx},wrap=1"


class Dev:
    def __init__(self, name):
        self.name, self.r = name, {}

    def s(self, oid, v): self.r[oid] = ("4", v)
    def i(self, oid, v): self.r[oid] = ("2", str(v))
    def oid(self, oid, v): self.r[oid] = ("6", v)
    def g(self, oid, v): self.r[oid] = ("66", str(v))
    def hexs(self, oid, v): self.r[oid] = ("4x", v)
    def num(self, oid, tag, spec): self.r[oid] = (f"{tag}:numeric", spec)

    def system(self, descr, objid, name, loc):
        self.s("1.3.6.1.2.1.1.1.0", descr)
        self.oid("1.3.6.1.2.1.1.2.0", objid)
        self.num("1.3.6.1.2.1.1.3.0", "67", "function=fabs%0,cumulative=1,rate=1,offset=100,initial=8640000,min=0,max=4294967295,wrap=1")
        self.s("1.3.6.1.2.1.1.4.0", "netops@example.lab")
        self.s("1.3.6.1.2.1.1.5.0", name)
        self.s("1.3.6.1.2.1.1.6.0", loc)
        self.i("1.3.6.1.2.1.1.7.0", 78)

    def interfaces(self, ports):
        """ports: list of (name, ifType, speed_bps, oper_up, in_Bps, out_Bps)"""
        self.i("1.3.6.1.2.1.2.1.0", len(ports))
        for n, (name, typ, speed, up, inb, outb) in enumerate(ports, 1):
            t = f"1.3.6.1.2.1.2.2.1.%d.{n}"
            x = f"1.3.6.1.2.1.31.1.1.1.%d.{n}"
            self.i(t % 1, n)
            self.s(t % 2, name)
            self.i(t % 3, typ)
            self.i(t % 4, 1500)
            self.g(t % 5, min(speed, C32))
            self.hexs(t % 6, "00AABB%06X" % (hash(self.name + name) & 0xFFFFFF))
            self.i(t % 7, 1)
            self.i(t % 8, 1 if up else 2)
            self.num(t % 10, "65", counter(inb if up else 0))
            self.num(t % 11, "65", counter(inb // 800 if up else 0))
            self.num(t % 14, "65", counter(1 if up and n % 3 == 0 else 0))
            self.num(t % 16, "65", counter(outb if up else 0))
            self.num(t % 17, "65", counter(outb // 800 if up else 0))
            self.num(t % 20, "65", counter(0))
            self.s(x % 1, name)
            self.num(x % 6, "70", counter(inb if up else 0, mx=2**64 - 1))
            self.num(x % 10, "70", counter(outb if up else 0, mx=2**64 - 1))
            self.g(x % 15, speed // 1_000_000)
            self.s(x % 18, f"{self.name} {name}")

    def cisco_health(self, temp_base=38):
        b = "1.3.6.1.4.1.9.9.109.1.1.1.1"   # cpmCPUTotalTable
        self.i(f"{b}.2.1", 1001)
        self.num(f"{b}.6.1", "66", gauge(14, 6, 0.11))   # 5 sec
        self.num(f"{b}.7.1", "66", gauge(12, 4, 0.05))   # 1 min
        self.num(f"{b}.8.1", "66", gauge(11, 2, 0.02))   # 5 min
        m = "1.3.6.1.4.1.9.9.48.1.1.1"      # ciscoMemoryPoolTable
        self.s(f"{m}.2.1", "Processor")
        self.g(f"{m}.3.1", 1)
        self.num(f"{m}.5.1", "66", gauge(1_200_000_000, 80_000_000, 0.03, 0, C32))   # used
        self.num(f"{m}.6.1", "66", gauge(2_800_000_000, 80_000_000, 0.03, 0, C32))   # free
        e = "1.3.6.1.4.1.9.9.13.1.3.1"      # ciscoEnvMonTemperatureStatusTable
        self.s(f"{e}.2.1", "Chassis Temperature")
        self.num(f"{e}.3.1", "66", gauge(temp_base, 3, 0.01, 0, 120))
        self.i(f"{e}.6.1", 1)               # normal

    def write(self):
        key = lambda o: tuple(int(p) for p in o.split("."))
        with open(os.path.join(OUT, self.name + ".snmprec"), "w") as f:
            for o in sorted(self.r, key=key):
                tag, val = self.r[o]
                f.write(f"{o}|{tag}|{val}\n")


# ---- Cisco ISR router
d = Dev("cisco-router")
d.system("Cisco IOS XE Software, Version 17.06.03, ISR4331/K9 (X86), RELEASE SOFTWARE (fc4)",
         "1.3.6.1.4.1.9.1.2279", "RTR-LAB-01", "Lab Rack A / U12")
d.interfaces([("GigabitEthernet0/0/0", 6, 1_000_000_000, True, 2_500_000, 1_200_000),
              ("GigabitEthernet0/0/1", 6, 1_000_000_000, True, 900_000, 1_800_000),
              ("GigabitEthernet0/0/2", 6, 1_000_000_000, False, 0, 0),
              ("Tunnel0", 131, 100_000_000, True, 150_000, 120_000),
              ("Loopback0", 24, 0, True, 0, 0)])
d.cisco_health(41); d.write()

# ---- Cisco Catalyst switch
d = Dev("cisco-switch")
d.system("Cisco IOS Software [Cupertino], Catalyst L3 Switch Software (CAT9K_LITE_IOSXE), Version 17.9.4, C9200L-24T-4G",
         "1.3.6.1.4.1.9.1.2530", "SW-LAB-01", "Lab Rack A / U10")
ports = [(f"GigabitEthernet1/0/{n}", 6, 1_000_000_000, n not in (5, 9), 300_000 + n * 70_000, 200_000 + n * 40_000) for n in range(1, 13)]
ports += [("GigabitEthernet1/1/1", 6, 1_000_000_000, True, 6_000_000, 8_000_000), ("Vlan1", 53, 1_000_000_000, True, 50_000, 40_000)]
d.interfaces(ports); d.cisco_health(36); d.write()

# ---- generic L2 switch
d = Dev("switch")
d.system("Generic 24-port Gigabit Managed Switch, firmware 2.1.7", "1.3.6.1.4.1.8072.3.2.10", "SW-ACCESS-02", "Lab Rack B / U5")
d.interfaces([(f"port{n}", 6, 1_000_000_000, n != 4, 200_000 + n * 50_000, 150_000 + n * 30_000) for n in range(1, 9)])
d.write()

# ---- FortiGate
d = Dev("fortigate")
d.system("FortiGate-60F v7.2.5,build1517,230731 (GA.M)", "1.3.6.1.4.1.12356.101.1.6006", "FGT-LAB-01", "Lab Rack A / U14")
d.interfaces([("wan1", 6, 1_000_000_000, True, 4_000_000, 1_500_000), ("wan2", 6, 1_000_000_000, False, 0, 0),
              ("lan", 6, 1_000_000_000, True, 1_500_000, 4_000_000), ("dmz", 6, 1_000_000_000, True, 200_000, 100_000),
              ("ssl.root", 131, 0, True, 80_000, 60_000)])
f = "1.3.6.1.4.1.12356.101.4.1"   # FORTINET-FORTIGATE-MIB fgSystemInfo
d.s(f"{f}.1.0", "v7.2.5,build1517,230731 (GA.M)")
d.num(f"{f}.3.0", "66", gauge(22, 12, 0.07))      # fgSysCpuUsage %
d.num(f"{f}.4.0", "66", gauge(48, 5, 0.03))       # fgSysMemUsage %
d.g(f"{f}.5.0", 4_000_000)                        # fgSysMemCapacity KB
d.num(f"{f}.6.0", "66", gauge(31, 1, 0.01))       # fgSysDiskUsage MB
d.g(f"{f}.7.0", 120_000)                          # fgSysDiskCapacity MB
d.num(f"{f}.8.0", "66", gauge(5200, 1500, 0.04, 0, 100000))   # fgSysSesCount
d.num(f"{f}.11.0", "66", gauge(180, 60, 0.09, 0, 5000))       # fgSysSesRate1
d.i("1.3.6.1.4.1.12356.101.13.1.1.0", 1)          # fgHaSystemMode: standalone
t = "1.3.6.1.4.1.12356.101.12.2.2.1"              # fgVpnTunTable
d.i(f"{t}.1.1", 1); d.s(f"{t}.2.1", "Site-to-HQ"); d.s(f"{t}.3.1", "Site-to-HQ"); d.i(f"{t}.20.1", 2)   # 2 = up
d.i(f"{t}.1.2", 2); d.s(f"{t}.2.2", "Site-to-Branch"); d.s(f"{t}.3.2", "Site-to-Branch"); d.i(f"{t}.20.2", 1)  # 1 = down
d.write()
print("generated", sorted(os.listdir(OUT)))
