#!/bin/sh
# Проверяет что tunnel_url существует и URL отвечает

if [ ! -f /shared/tunnel_url ]; then
    exit 1
fi

URL=$(cat /shared/tunnel_url)
if [ -z "$URL" ]; then
    exit 1
fi

wget -q --spider --timeout=5 "$URL" 2>/dev/null
