# netlab – realistic simulated network devices for PRTG

Four simulated devices (FortiGate, Cisco router, Cisco switch, generic switch) exposed over **SNMP** (UDP, host port 1161) and **REST** (ports 8441–8444).
SNMP and REST are driven by the same engine (`shared/simcore.py`), so a value seen over SNMP matches what the REST API reports.

## Realism
- Daily/weekly traffic curves (office, wan, server, idle, bursty), noise, bursts and surges, capped at link speed
- Counters (32/64-bit) integrated from a fixed boot time: monotonic, wrap correctly, uptime ~ real
- CPU (5s/1m/5m, per core), memory with slow drift, temperature, sessions, session setup rate
- Interface errors/discards, link flaps, scheduled outages, random reboots
- IPsec tunnels (up/down/flapping, in/out bytes), SSL-VPN users
- Network behaviour: packet loss, latency + jitter, SNMP rate limiting, device unreachable (timeouts / HTTP 504)

## Use
    docker compose up -d --build
SNMP community = device name: `fortigate`, `cisco-router`, `cisco-switch`, `switch` (v1/v2c, port 1161).
SNMPv3: user `simulator`, auth MD5 `auctoritas`, priv DES `privatus`, context = device name.

## Scenarios (hot reload, no restart)
Edit `scenarios/scenarios.json` (bind-mounted; picked up within ~2 s). Regenerate defaults with `python make_defaults.py`.
Enable named overlays through `"active_scenarios": [...]`:
`wan_flapping`, `fortigate_cpu_runaway`, `fortigate_memory_leak`, `vpn_unstable`, `vpn_branch_up`, `snmp_unreliable`,
`nightly_outage`, `reboot_loop`, `ddos_on_wan1`, `dirty_uplink`.
Per-device keys: `interfaces`, `cpu`, `mem`, `temp`, `sessions`, `network` (loss_pct, latency_ms, rate_limit_per_s, outages), `vpn`, `ssl_vpn`.

## REST (token for FortiGate: `fgt-test-token`, Cisco: admin/admin)
FortiGate (8441, FortiOS 7.2 format): `/api/v2/monitor/system/{status,resource/usage,performance/status,interface,firmware,ha-peer}`,
`/api/v2/monitor/vpn/{ipsec,ssl,ssl/stats}`, `/api/v2/monitor/firewall/session/summary`, `/api/v2/cmdb/firewall/policy`
→ for PRTG **FortiGate System Statistics** and **FortiGate VPN Overview** sensors.
Cisco RESTCONF (8442/8443), switch `/api/status` (8444), PRTG-ready JSON `/prtg/sensors` on all.
`API_LOG=1` logs every request (`docker compose logs -f rest`) to see exactly what a sensor calls.
Set `TLS=1` for HTTPS (self-signed).

## Limits
Synthetic data; only the OIDs/endpoints implemented respond. Not a full device emulation.
