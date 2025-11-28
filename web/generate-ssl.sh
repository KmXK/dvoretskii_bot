#!/bin/sh
# Генерация самоподписанного SSL сертификата для Vite

openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout key.pem \
    -out cert.pem \
    -days 365 \
    -subj "/C=RU/ST=State/L=City/O=Organization/CN=localhost"

echo "SSL сертификат создан: key.pem и cert.pem"
echo "Теперь установите VITE_HTTPS=true в docker-compose.yml для web сервиса"

