#!/bin/sh
# Ждёт появления tunnel URL и запускает команду

echo "Ожидаю tunnel URL..."

while [ ! -f /shared/tunnel_url ]; do
    sleep 1
done

export WEB_APP_URL=$(cat /shared/tunnel_url)
echo "WEB_APP_URL=$WEB_APP_URL"

exec "$@"

