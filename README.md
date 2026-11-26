# Docker labs

Docker-based test targets for PRTG monitoring.

- [netlab](netlab/) - simulated FortiGate, Cisco router/switch and generic switch (SNMP + REST)
- [prtg-target](prtg-target/) - Apache/PHP test target for HTTP, HTTP Advanced, REST Custom v2 and HTTP Push sensors
- [netlab-ot](netlab-ot/) - MQTT (Mosquitto), Modbus TCP and NetApp ONTAP simulators with fault injection, debug logs and a support bundle; PRTG sensor settings in [docs/PRTG_SETUP.md](netlab-ot/docs/PRTG_SETUP.md)

Each folder: `docker compose up -d --build`
