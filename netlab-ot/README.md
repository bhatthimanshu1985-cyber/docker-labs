# netlab-ot: MQTT, Modbus TCP and NetApp ONTAP lab with fault injection and full debug trail

Purpose: reproduce a customer's problem, show exactly what happened on the wire/API, and hand evidence to development.

    docker compose up -d --build
    ./labctl status

| Simulator | Ports | What it is |
|---|---|---|
| Mosquitto 2 | 1883 (MQTT), 8883 (TLS, lab CA), 9001 (WebSocket) | Real broker, auth on (lab/labpass, device/devpass), log_type all |
| mqtt-sim | 9101 control | 3 devices (plc-01 QoS1, sensor-02 QoS0, gateway-03 QoS2 JSON), Last Will + retained status, "tap" logger of every message |
| modbus-sim | 502 (TCP), 9102 control | Own Modbus TCP server. Unit 1 PLC, unit 2 energy meter (float32), unit 3 VFD. FC 1-6, 15, 16 |
| netapp-sim | 8080 HTTP, 443 HTTPS (self-signed) | ONTAP 9.12 REST (/api/...) + ZAPI (/servlets/netapp.servlets.admin.XMLrequest_filer). admin/netapp123 |

PRTG sensor settings for every simulator: see docs/PRTG_SETUP.md

## Reproduce an issue
    ./labctl scenario list
    ./labctl scenario netapp-node-down        # or any other
    ./labctl fault modbus delay_ms --value 3000
    ./labctl action mqtt kill_connection --target plc-01 --value 60
    ./labctl scenario reset

## See what happened (debug data)
- `./labctl timeline -n 100 [--grep text]`  merged chronological view of all simulators; rows marked FAULTS were produced while a fault was active
- `logs/<sim>.jsonl`  full history. Modbus: request AND response hex frames, unit/function/address/count, exception, latency.
  NetApp: method, path, query, headers (auth redacted), body, status, response preview, latency, injected-fault note.
  MQTT: connects/disconnects with reason codes, every publish and every message seen by the tap.
- Mosquitto broker log: `docker compose logs -f mosquitto` (client ids, QoS, retain, sizes, keepalive timeouts, LWT)
- `./labctl logs <sim> -n 50`, `./labctl status` (current values + active faults)
- Packet capture: `docker compose --profile capture up capture` -> logs/capture.pcap (Wireshark)
- `./labctl bundle`  -> support-bundle-<time>.tar.gz (state, logs, docker logs, pcap) to attach to an escalation

## Faults
Modbus: word_swap, delay_ms, drop_connection (probability), no_response, exception (--target unit, --value code), idle_timeout, max_connections, freeze_values, garbage, lenient_unit.
  Quirks that mimic real devices: writes to read-only registers -> exception 2, unknown unit id -> exception 11, quantity limits -> exception 3.
NetApp: volume_full, aggr_full, volume_offline, disk_fail, node_down, snapmirror_broken, snapmirror_lag, high_latency, port_down (target node:port), overtemp, api_delay_ms, api_error (HTTP code), auth_fail. Each creates matching EMS events.
MQTT: pause, garbage (per device), interval_factor; actions kill_connection (ungraceful, triggers LWT), burst, oversize, publish ("topic|payload").
Generic API: GET /_lab/state, /_lab/log; POST /_lab/fault {"name","target","value"}; DELETE /_lab/fault; POST /_lab/action.

## Point your monitoring tool at it
Use the Docker host IP. Modbus: port 502, unit 1/2/3 (PLC regs: 0 temp x10, 1 pressure x100, 2 setpoint (writable), 3 rpm, 4-5 counter32, 6 status; coils 0-2; meter floats: V, I, kW, Hz, kWh at regs 0,2,4,6,8).
NetApp: HTTPS 443 or HTTP 8080, basic auth. MQTT: 1883, user lab/labpass, topics factory/#, factory/<device>/status (retained online/offline).
The /_lab control API is unauthenticated: keep this lab on a trusted network.
