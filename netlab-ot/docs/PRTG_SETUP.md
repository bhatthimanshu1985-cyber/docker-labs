# Adding the lab to PRTG

Create one PRTG **device** per simulated target, all with the Docker host IP (same IP, different ports/credentials in the sensors).
Verified against the PRTG manual sensor list; the simulators themselves could not be tested against a real PRTG instance, so
use the first-run check at the bottom if a sensor misbehaves.

## Modbus (sensor: **Modbus TCP Custom**) - port 502
| Setting | Value |
|---|---|
| Port | 502 |
| Unit ID | 1 = PLC, 2 = energy meter, 3 = VFD |
| Byte Order | **Big-endian (AB CD)** is what the simulator sends. Use `./labctl scenario modbus-float-wordswap` (CD AB), `modbus-byteorder-badc` (BA DC) or `modbus-byteorder-dcba` (DC BA) to reproduce a wrong-byte-order customer |

Channels (holding and input registers hold the same data; PRTG drops the 3xxxx/4xxxx prefix, so holding register 40001 = address 0 or 1 depending on the PRTG
addressing convention. The simulator log shows the exact address PRTG asks for: `./labctl timeline --grep modbus`):
| Unit | Register | Data type in PRTG | Scale | Meaning |
|---|---|---|---|---|
| 1 | 0 | Unsigned 16 | 0.1 | Temperature C |
| 1 | 1 | Unsigned 16 | 0.01 | Pressure bar |
| 1 | 2 | Unsigned 16 | 0.1 | Setpoint (writable) |
| 1 | 3 | Unsigned 16 | 1 | Motor rpm |
| 1 | 4-5 | Unsigned 32 | 1 | Counter |
| 1 | 6 | Unsigned 16 | 1 | Status bits (1 run, 2 overtemp) |
| 2 | 0 / 2 / 4 / 6 / 8 | Float 32 | 1 | Voltage V / Current A / Power kW / Frequency Hz / Energy kWh |
| 2 | 12 | Signed 16 | 0.1 | Temperature (negative) |
| 2 | 20-23 | Double (64-bit) | 1 | Test double |
| 3 | 0 / 1 | Unsigned 16 | 0.01 / 0.1 | VFD output frequency / current |
Coils 0-2 and discrete inputs 0-2 exist on unit 1 (door, e-stop, overtemp alarm).

## MQTT - broker 1883 (TLS 8883), user `lab` / `labpass`
| PRTG sensor | Settings |
|---|---|
| **MQTT Round Trip** | Port 1883 (or 8883 with TLS: the lab CA is generated inside the broker image, so use the "no certificate validation" option), user lab / labpass. Default topic `PRTG/roundtrip/%sensorid` works (no ACLs). Reproduce: stop the broker, or `./labctl scenario mqtt-message-burst` |
| **MQTT Statistics** | Same connection. Reads the broker `$SYS` topics, which Mosquitto publishes every 10 s |
| **MQTT Subscribe Custom** | Topic `factory/line1/temperature`, JSONPath `$.value` (also `factory/line1/pressure`, `factory/line2/humidity`). Multi-value: topic `factory/line1/plc-01`, JSONPaths `$.temperature`, `$.pressure`, `$.rpm`, `$.counter`. Gateway: `factory/gateway/telemetry` with `$.temp`, `$.rssi`. Wildcards work: `factory/+/temperature` |
Status topics: `factory/<device>/status` (retained `online` / `offline` via Last Will).
Reproduce: `mqtt-stale-data` (sensor keeps its old value / no new message), `mqtt-garbage-payload` (JSONPath fails), `mqtt-device-dropout`.

## NetApp - HTTPS 4443 (or HTTP 8081; container ports 443/8080), set the port in the device credentials, user `admin` / `netapp123`
Put the credentials on the device (PRTG NetApp v2 sensors read them from the parent device).
| PRTG sensor | API used | Lab data |
|---|---|---|
| **NetApp Aggregate v2 / Volume v2 / LUN v2 / I/O v2 / Physical Disk v2 / System Health v2** | ONTAP REST (ONTAP 9.6+), simulator reports 9.12.1 | aggr1_n1, aggr1_n2; vol_data01, vol_db01, vol_cifs_home, vol_vmware_ds1, vol_backup; 1 LUN; disks 1.0.0-1.0.23; nodes labcluster01-01/-02 |
| Older **NetApp Aggregate / Volume / ... (non-v2)** | ONTAPI (ZAPI, SOAP/XML) | implemented: system-get-version, system-get-ontapi-version, cluster-identity-get, system-node-get-iter, aggr-get-iter, volume-get-iter |
Reproduce: `netapp-volume-full`, `netapp-aggr-nearly-full`, `netapp-volume-offline`, `netapp-disk-failure`, `netapp-node-down`, `netapp-api-slow`, `netapp-auth-fail`.

## SNMP / REST / HTTP devices (earlier labs)
`netlab` (FortiGate, Cisco router/switch, generic switch: SNMP + REST) and `prtg-target` (Apache: HTTP, HTTP Advanced, REST Custom v2, HTTP Push) are in the same repository.

## First-run check when a sensor is red
1. `./labctl timeline -n 50` shows what PRTG just asked and what the simulator answered (with hex frames for Modbus).
2. `./labctl logs netapp --event unimplemented_endpoint` (and `unimplemented_zapi`): any REST/ZAPI call PRTG made that the simulator does not model yet. Send those lines to the lab maintainer and the endpoint gets added.
3. In PRTG, set the sensor's Debug option "Store result" to compare PRTG's view with the lab log.
