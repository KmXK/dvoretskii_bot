#!/bin/sh
# Ждёт появления tunnel URL и запускает команду

rm -f /shared/tunnel_url
echo "Ожидаю tunnel URL..."

while [ ! -f /shared/tunnel_url ]; do
    sleep 1
done

export WEB_APP_URL=$(cat /shared/tunnel_url)
echo "WEB_APP_URL=$WEB_APP_URL"

exec "$@"

