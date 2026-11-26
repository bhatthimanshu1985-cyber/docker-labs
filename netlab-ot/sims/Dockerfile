FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir fastapi "uvicorn[standard]" "paho-mqtt>=2.0"
WORKDIR /srv
RUN openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=netapp-lab" -keyout key.pem -out cert.pem
COPY labcommon.py mqtt_sim.py modbus_sim.py netapp_sim.py ./
CMD ["python", "modbus_sim.py"]
