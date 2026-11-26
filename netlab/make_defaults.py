"""Regenerates scenarios/scenarios.json (device structure + default behaviour + named scenario library).
Run: python make_defaults.py   -- then edit scenarios.json by hand for customer-specific behaviour."""
import json

def ifc(name, typ, speed, i, o, profile, **kw):
    d = {"type": typ, "speed": speed, "in_bps": i, "out_bps": o, "profile": profile}
    d.update(kw); return d

G = 1_000_000_000
fw_if = {
    "wan1": ifc("wan1", 6, G, 4_000_000, 1_500_000, "wan", role="wan", flaps_per_day=0.2, flap_s=[20, 90], errors_per_hour=0.6),
    "wan2": ifc("wan2", 6, G, 0, 0, "idle", status="down"),
    "lan":  ifc("lan", 6, G, 1_500_000, 4_000_000, "office", errors_per_hour=0.2),
    "dmz":  ifc("dmz", 6, G, 200_000, 100_000, "server"),
    "ssl.root": ifc("ssl.root", 131, 0, 80_000, 60_000, "office", bursts_per_hour=3),
}
rt_if = {
    "GigabitEthernet0/0/0": ifc("", 6, G, 2_500_000, 1_200_000, "wan", role="wan", errors_per_hour=0.4),
    "GigabitEthernet0/0/1": ifc("", 6, G, 900_000, 1_800_000, "office"),
    "GigabitEthernet0/0/2": ifc("", 6, G, 0, 0, "idle", status="down"),
    "Tunnel0": ifc("", 131, 100_000_000, 150_000, 120_000, "wan", flaps_per_day=0.5, flap_s=[30, 240]),
    "Loopback0": ifc("", 24, 0, 0, 0, "idle"),
}
sw_if = {f"GigabitEthernet1/0/{n}": ifc("", 6, G, 300_000 + n * 70_000, 200_000 + n * 40_000, "office",
                                         flaps_per_day=0.3 if n % 4 == 0 else 0, errors_per_hour=0.1 + (n % 3) * 0.4,
                                         **({"status": "down"} if n in (5, 9) else {})) for n in range(1, 13)}
sw_if["GigabitEthernet1/1/1"] = ifc("", 6, G, 2_500_000, 3_000_000, "server", bursts_per_hour=10)
sw_if["Vlan1"] = ifc("", 53, G, 50_000, 40_000, "office")
gs_if = {f"port{n}": ifc("", 6, G, 200_000 + n * 50_000, 150_000 + n * 30_000, "office", **({"status": "down"} if n == 4 else {})) for n in range(1, 9)}

cfg = {
    "_readme": "Edit and save: values are hot-reloaded within ~2 s (no restart). Structure changes (adding/removing interfaces, device descr) need: docker compose up -d --build. active_scenarios lists named scenarios (see 'scenarios') that are merged on top.",
    "timezone": "Europe/Berlin",
    "seed": 42,
    "active_scenarios": ["vpn_branch_up"],
    "devices": {
        "fortigate": {
            "kind": "fortigate", "descr": "FortiGate-60F v7.2.5,build1517,230731 (GA.M)", "objid": "1.3.6.1.4.1.12356.101.1.6006",
            "sysname": "FGT-LAB-01", "location": "Lab Rack A / U14", "boot": "2026-11-12T03:12:00", "reboot_downtime_s": 150,
            "load_profile": "office",
            "cpu": {"base": 8, "load_amp": 20, "noise": 3, "spike_per_hour": 2, "spike_amp": 30},
            "mem": {"base": 44, "load_amp": 6, "drift_per_day": 0.06, "leak_reset_days": 0, "noise": 0.8},
            "temp": {"base": 38, "cpu_coupling": 0.12},
            "sessions": {"base": 3500, "per_mbps": 45, "noise": 150, "spike_per_hour": 0.5, "spike_amp": 6000},
            "network": {"loss_pct": 0, "latency_ms": [2, 20], "outages": [], "random_outages_per_day": 0},
            "interfaces": fw_if,
            "vpn": {"Site-to-HQ": {"state": "up", "remote": "192.0.2.10", "in_bps": 90000, "out_bps": 70000, "flaps_per_day": 0.5, "flap_s": [40, 300]},
                    "Site-to-Branch": {"state": "down", "remote": "192.0.2.20"}},
            "ssl_vpn": {"users_max": 8}},
        "cisco-router": {
            "kind": "cisco", "descr": "Cisco IOS XE Software, Version 17.06.03, ISR4331/K9 (X86), RELEASE SOFTWARE (fc4)", "objid": "1.3.6.1.4.1.9.1.2279",
            "sysname": "RTR-LAB-01", "location": "Lab Rack A / U12", "boot": "2026-11-05T02:40:00", "reboot_downtime_s": 240,
            "cpu": {"base": 6, "load_amp": 9, "noise": 2, "spike_per_hour": 1.5, "spike_amp": 25},
            "mem": {"base": 30, "load_amp": 3, "drift_per_day": 0.03, "noise": 0.4},
            "temp": {"base": 40, "cpu_coupling": 0.08},
            "network": {"loss_pct": 0, "latency_ms": [3, 25]}, "interfaces": rt_if},
        "cisco-switch": {
            "kind": "cisco", "descr": "Cisco IOS Software [Cupertino], Catalyst L3 Switch Software (CAT9K_LITE_IOSXE), Version 17.9.4, C9200L-24T-4G", "objid": "1.3.6.1.4.1.9.1.2530",
            "sysname": "SW-LAB-01", "location": "Lab Rack A / U10", "boot": "2026-11-10T01:10:00", "reboot_downtime_s": 300,
            "cpu": {"base": 4, "load_amp": 7, "noise": 1.5, "spike_per_hour": 1, "spike_amp": 18},
            "mem": {"base": 28, "load_amp": 2, "drift_per_day": 0.02, "noise": 0.3},
            "temp": {"base": 35, "cpu_coupling": 0.06},
            "network": {"loss_pct": 0, "latency_ms": [2, 18]}, "interfaces": sw_if},
        "switch": {
            "kind": "generic", "descr": "Generic 24-port Gigabit Managed Switch, firmware 2.1.7", "objid": "1.3.6.1.4.1.8072.3.2.10",
            "sysname": "SW-ACCESS-02", "location": "Lab Rack B / U5", "boot": "2026-10-29T04:00:00",
            "cpu": {"base": 5, "load_amp": 5, "noise": 1}, "mem": {"base": 35, "load_amp": 1, "noise": 0.3},
            "temp": {"base": 41, "cpu_coupling": 0.05},
            "network": {"loss_pct": 0, "latency_ms": [4, 30]}, "interfaces": gs_if},
    },
    "scenarios": {
        "wan_flapping": {"devices": {"fortigate": {"interfaces": {"wan1": {"flaps_per_day": 24, "flap_s": [10, 60]}}}}},
        "fortigate_cpu_runaway": {"devices": {"fortigate": {"cpu": {"base": 78, "load_amp": 12, "spike_per_hour": 6, "spike_amp": 20}}}},
        "fortigate_memory_leak": {"devices": {"fortigate": {"mem": {"drift_per_day": 12, "leak_reset_days": 7}}}},
        "vpn_unstable": {"devices": {"fortigate": {"vpn": {"Site-to-HQ": {"flaps_per_day": 30, "flap_s": [20, 120]}}}}},
        "vpn_branch_up": {"devices": {"fortigate": {"vpn": {"Site-to-Branch": {"state": "up", "in_bps": 40000, "out_bps": 30000}}}}},
        "snmp_unreliable": {"devices": {d: {"network": {"loss_pct": 25, "latency_ms": [200, 2500]}} for d in ("fortigate", "cisco-router", "cisco-switch", "switch")}},
        "nightly_outage": {"devices": {d: {"network": {"outages": [{"at": "02:00", "duration_s": 600, "days": "daily"}]}} for d in ("cisco-router", "switch")}},
        "reboot_loop": {"devices": {"cisco-switch": {"reboot_mtbf_days": 0.2, "reboot_downtime_s": 180}}},
        "ddos_on_wan1": {"devices": {"fortigate": {"interfaces": {"wan1": {"surges": [{"at": "21:00", "duration_s": 1800, "days": "daily", "factor": 12}]}},
                                                      "sessions": {"spike_per_hour": 4, "spike_amp": 40000}}}},
        "dirty_uplink": {"devices": {"cisco-switch": {"interfaces": {"GigabitEthernet1/1/1": {"errors_per_hour": 400, "discards_per_hour": 300, "flaps_per_day": 8}}}}},
    },
}
json.dump(cfg, open("scenarios/scenarios.json", "w"), indent=1)
print("wrote scenarios/scenarios.json")
