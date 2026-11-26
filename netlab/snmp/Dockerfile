FROM python:3.11-slim
RUN pip install --no-cache-dir snmpsim-lextudio tzdata
ENV TZ=Europe/Berlin SCENARIO_FILE=/srv/scenarios/scenarios.json SIMCORE_PATH=/srv
WORKDIR /srv
COPY shared/simcore.py snmp/gen.py snmp/proxy.py snmp/start.sh ./
COPY snmp/variation ./variation
# default scenario file (compose bind-mounts ./scenarios over this so it can be edited live)
COPY scenarios/scenarios.json ./scenarios/scenarios.json
RUN python gen.py /srv/scenarios/scenarios.json /srv/data && chmod +x start.sh
EXPOSE 161/udp
# community string = device (fortigate | cisco-router | cisco-switch | switch); SNMPv3 user "simulator", context = device name
CMD ["./start.sh"]
