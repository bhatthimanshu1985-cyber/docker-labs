#!/bin/sh
# Users: lab/labpass (simulators + you), device/devpass.  MQTT_ALLOW_ANON=true allows anonymous clients.
mosquitto_passwd -b -c /mosquitto/config/passwd lab "${MQTT_LAB_PASS:-labpass}"
mosquitto_passwd -b /mosquitto/config/passwd device "${MQTT_DEVICE_PASS:-devpass}"
chown mosquitto:mosquitto /mosquitto/config/passwd /mosquitto/data 2>/dev/null
[ "$MQTT_ALLOW_ANON" = "true" ] && sed -i 's/allow_anonymous false/allow_anonymous true/' /mosquitto/config/mosquitto.conf
exec "$@"
