#!/bin/sh
# Sends data to a PRTG "HTTP Push Data" sensor every PUSH_INTERVAL seconds.
# PRTG_PUSH_URL example: http://192.168.1.10:5050/MY_IDENTIFICATION_TOKEN
INTERVAL="${PUSH_INTERVAL:-60}"
while true; do
  LOAD=$(cut -d' ' -f1 /proc/loadavg)
  MEM=$(awk '/MemAvailable/{a=$2}/MemTotal/{t=$2}END{printf "%.1f",(t-a)*100/t}' /proc/meminfo)
  curl -s -m 10 -X POST -H "Content-Type: application/json" \
    -d "{\"prtg\":{\"result\":[{\"channel\":\"Load\",\"value\":$LOAD,\"float\":1},{\"channel\":\"Memory used\",\"value\":$MEM,\"unit\":\"Percent\",\"float\":1}],\"text\":\"Pushed from $(hostname)\"}}" \
    "$PRTG_PUSH_URL" >/dev/null || echo "push failed"
  sleep "$INTERVAL"
done
