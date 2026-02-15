#!/bin/sh

LOCAL_PORT=${LOCAL_PORT:-80}
LOCAL_HOST=${LOCAL_HOST:-localhost}
MAX_BACKOFF=60
ATTEMPT=0

while true; do
    rm -f /shared/tunnel_url
    ATTEMPT=$((ATTEMPT + 1))

    echo "[attempt $ATTEMPT] Starting localhost.run tunnel (${LOCAL_HOST}:${LOCAL_PORT})..."

    ssh -R 80:${LOCAL_HOST}:${LOCAL_PORT} \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ServerAliveInterval=15 \
        -o ServerAliveCountMax=2 \
        -o ExitOnForwardFailure=yes \
        -o ConnectTimeout=10 \
        -T -n \
        nokey@localhost.run 2>&1 | while read line; do
            echo "$line"
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

    rm -f /shared/tunnel_url
    BACKOFF=$((ATTEMPT > MAX_BACKOFF ? MAX_BACKOFF : ATTEMPT * 2))
    echo "[attempt $ATTEMPT] Tunnel disconnected. Reconnecting in ${BACKOFF}s..."
    sleep "$BACKOFF"
done
