#!/bin/sh
# snmpsim backend (private) + network-behaviour front-end on UDP 161
snmpsim-command-responder --data-dir=/srv/data --variation-modules-dir=/srv/variation \
  --agent-udpv4-endpoint=127.0.0.1:16100 --process-user=nobody --process-group=nogroup &
sleep 3
exec python /srv/proxy.py
