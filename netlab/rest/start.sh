#!/bin/sh
# One mock REST endpoint per device, each on its own port.
SSL=""
[ "$TLS" = "1" ] && SSL="--ssl-keyfile /srv/key.pem --ssl-certfile /srv/cert.pem"
DEVICE=fortigate     uvicorn app:app --host 0.0.0.0 --port 8441 $SSL &
DEVICE=cisco-router  uvicorn app:app --host 0.0.0.0 --port 8442 $SSL &
DEVICE=cisco-switch  uvicorn app:app --host 0.0.0.0 --port 8443 $SSL &
DEVICE=switch        uvicorn app:app --host 0.0.0.0 --port 8444 $SSL &
wait
