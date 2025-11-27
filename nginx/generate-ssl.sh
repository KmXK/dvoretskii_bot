#!/bin/sh
# Генерация самоподписанного SSL сертификата для разработки

mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout ssl/key.pem \
    -out ssl/cert.pem \
    -subj "/C=RU/ST=State/L=City/O=Organization/CN=localhost"

echo "SSL сертификат создан в папке ssl/"

