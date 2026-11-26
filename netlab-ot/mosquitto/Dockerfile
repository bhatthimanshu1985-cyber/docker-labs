FROM eclipse-mosquitto:2
RUN apk add --no-cache openssl \
 && mkdir -p /mosquitto/certs /mosquitto/log \
 && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=lab-ca" -keyout /tmp/ca.key -out /mosquitto/certs/ca.crt \
 && openssl req -newkey rsa:2048 -nodes -subj "/CN=mosquitto" -addext "subjectAltName=DNS:mosquitto,DNS:localhost,IP:127.0.0.1" -keyout /mosquitto/certs/server.key -out /tmp/server.csr \
 && printf "subjectAltName=DNS:mosquitto,DNS:localhost,IP:127.0.0.1" > /tmp/ext.cnf \
 && openssl x509 -req -in /tmp/server.csr -CA /mosquitto/certs/ca.crt -CAkey /tmp/ca.key -CAcreateserial -days 3650 -extfile /tmp/ext.cnf -out /mosquitto/certs/server.crt \
 && chown -R mosquitto:mosquitto /mosquitto/certs /mosquitto/log
COPY mosquitto.conf /mosquitto/config/mosquitto.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/sbin/mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]
