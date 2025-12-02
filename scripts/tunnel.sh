#!/bin/sh

LOCAL_PORT=${LOCAL_PORT:-80}
LOCAL_HOST=${LOCAL_HOST:-localhost}

rm -f /shared/tunnel_url

echo "Starting localhost.run tunnel..."
echo "Forwarding ${LOCAL_HOST}:${LOCAL_PORT} to localhost.run"

exec ssh -R 80:${LOCAL_HOST}:${LOCAL_PORT} \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -T -n \
    nokey@localhost.run 2>&1 | while read line; do
        echo "$line"
        # Ищем URL в выводе
        if echo "$line" | grep -q 'tunneled with tls termination'; then
            URL=$(echo "$line" | grep -oE 'https://[^ ]+')
            echo ""
            echo "================================"
            echo "TUNNEL URL: $URL"
            echo "================================"
            echo ""
            echo "$URL" > /shared/tunnel_url
        fi
    done