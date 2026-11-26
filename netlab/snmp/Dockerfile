FROM python:3.11-slim
RUN pip install --no-cache-dir snmpsim-lextudio
WORKDIR /srv
COPY gen.py .
RUN python gen.py /srv/data
EXPOSE 161/udp
# community string = file name: fortigate, cisco-router, cisco-switch, switch
CMD ["snmpsim-command-responder", "--data-dir=/srv/data", "--agent-udpv4-endpoint=0.0.0.0:161", "--process-user=nobody", "--process-group=nogroup"]
