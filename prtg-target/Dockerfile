FROM php:8.3-apache
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY site/ /var/www/html/
COPY push.sh entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/push.sh /usr/local/bin/entrypoint.sh
EXPOSE 80
ENTRYPOINT ["entrypoint.sh"]
CMD ["apache2-foreground"]
