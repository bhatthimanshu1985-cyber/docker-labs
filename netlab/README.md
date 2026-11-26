# Netlab: simulated FortiGate, Cisco router/switch, generic switch
docker compose up -d --build

SNMP (UDP 161, v2c). Community string selects the device:
  fortigate | cisco-router | cisco-switch | switch
REST (HTTP; set TLS=1 in compose for HTTPS):
  8441 FortiGate     token: fgt-test-token (Bearer header or ?access_token=)
  8442 Cisco router  RESTCONF, basic auth admin/admin
  8443 Cisco switch  RESTCONF, basic auth admin/admin
  8444 generic switch GET /api/status (no auth)
  Every port also has /prtg/sensors (no auth): PRTG JSON for the REST Custom v2 sensor.

PRTG: add the Docker host IP as a device (one per simulated device, same IP), set the SNMP community per device.
SNMP sensors: SNMP System Uptime, SNMP Traffic (ifTable), SNMP Library, SNMP Custom (OIDs below).
 Cisco CPU 5min  1.3.6.1.4.1.9.9.109.1.1.1.1.8.1   Cisco mem used/free 1.3.6.1.4.1.9.9.48.1.1.1.5.1 / .6.1
 Cisco temp      1.3.6.1.4.1.9.9.13.1.3.1.3.1
 FortiGate CPU   1.3.6.1.4.1.12356.101.4.1.3.0   Mem 1.3.6.1.4.1.12356.101.4.1.4.0   Sessions 1.3.6.1.4.1.12356.101.4.1.8.0
 VPN tunnel status 1.3.6.1.4.1.12356.101.12.2.2.1.20.<n> (2=up, 1=down)
Note: if the host already runs snmpd on UDP 161, change the left side of "161:161/udp".
