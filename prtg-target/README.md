# PRTG test target (Apache in Docker)
docker compose up -d --build   -> http://HOST:8080
Find container IP: docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container>
(or just use the Linux host IP + port 8080)

PRTG sensors (device = HOST IP, port 8080):
- HTTP:            URL /health.php  (port 8080)
- HTTP Advanced:   URL /advanced.php, header "X-Api-Key: secret123", GET or POST, response must contain "Service status: RUNNING"
- REST Custom v2:  /api/v2/sensors.php  (PRTG JSON format, 4 channels)
- HTTP Push Data:  PRTG listens, this container pushes. Create the sensor, copy its URL (http://PRTG-IP:5050/TOKEN),
                   put it in PRTG_PUSH_URL in docker-compose.yml, restart.
