FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir fastapi "uvicorn[standard]" tzdata
ENV TZ=Europe/Berlin SCENARIO_FILE=/srv/scenarios/scenarios.json SIMCORE_PATH=/srv
WORKDIR /srv
RUN openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=netlab" -keyout key.pem -out cert.pem
COPY shared/simcore.py rest/app.py rest/start.sh ./
COPY scenarios/scenarios.json ./scenarios/scenarios.json
RUN chmod +x start.sh
EXPOSE 8441 8442 8443 8444
CMD ["./start.sh"]
