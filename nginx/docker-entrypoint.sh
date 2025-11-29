#!/bin/sh
set -e

# Если режим prod и нет сертификатов, создаем самоподписанный как fallback
if [ "$NGINX_MODE" = "prod" ]; then
    if [ ! -f "/etc/letsencrypt/live/${SSL_DOMAIN}/fullchain.pem" ]; then
        echo "Warning: Let's Encrypt certificate not found for ${SSL_DOMAIN}"
        echo "Creating self-signed certificate as fallback..."
        mkdir -p /etc/nginx/ssl
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout /etc/nginx/ssl/key.pem \
            -out /etc/nginx/ssl/cert.pem \
            -subj "/C=RU/ST=State/L=City/O=Organization/CN=${SSL_DOMAIN}"
        
        # Используем dev конфиг с самоподписанным сертификатом
        envsubst '$$SSL_DOMAIN' < /etc/nginx/templates/nginx-dev.conf.template > /etc/nginx/conf.d/default.conf
        sed -i 's|/etc/nginx/ssl/cert.pem|/etc/nginx/ssl/cert.pem|g' /etc/nginx/conf.d/default.conf
        sed -i 's|/etc/nginx/ssl/key.pem|/etc/nginx/ssl/key.pem|g' /etc/nginx/conf.d/default.conf
    else
        # Используем prod конфиг с Let's Encrypt
        envsubst '$$SSL_DOMAIN' < /etc/nginx/templates/nginx-prod.conf.template > /etc/nginx/conf.d/default.conf
        echo "Using Let's Encrypt certificate for ${SSL_DOMAIN}"
    fi
else
    # Dev режим - создаем самоподписанный сертификат
    if [ ! -f "/etc/nginx/ssl/cert.pem" ]; then
        mkdir -p /etc/nginx/ssl
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout /etc/nginx/ssl/key.pem \
            -out /etc/nginx/ssl/cert.pem \
            -subj "/C=RU/ST=State/L=City/O=Organization/CN=localhost"
    fi
    # Используем dev конфиг
    cp /etc/nginx/templates/nginx-dev.conf.template /etc/nginx/conf.d/default.conf
    echo "Using self-signed certificate (dev mode)"
fi

# Запускаем nginx напрямую (стандартный entrypoint nginx уже выполнил свою работу)
exec "$@"

