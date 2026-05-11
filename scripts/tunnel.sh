#!/bin/sh

LOCAL_PORT=${LOCAL_PORT:-80}
LOCAL_HOST=${LOCAL_HOST:-localhost}
KEY_SRC=/key/id_ed25519
KEY_DST=/tmp/tunnel_key
MAX_BACKOFF=60
ATTEMPT=0

SSH_KEY_ARGS=""
SSH_USER="nokey"

if [ -f "$KEY_SRC" ]; then
    cp "$KEY_SRC" "$KEY_DST"
    chmod 600 "$KEY_DST"
    SSH_KEY_ARGS="-i $KEY_DST -o IdentitiesOnly=yes"
    SSH_USER="tunnel"
    echo "[tunnel] Using SSH key from $KEY_SRC — URL will be stable"
else
    echo "[tunnel] No key at $KEY_SRC — using anonymous mode (random URL each connect)"
fi

while true; do
    rm -f /shared/tunnel_url
    ATTEMPT=$((ATTEMPT + 1))

    echo "[attempt $ATTEMPT] Starting localhost.run tunnel (${LOCAL_HOST}:${LOCAL_PORT})..."

    ssh -R 80:${LOCAL_HOST}:${LOCAL_PORT} \
        $SSH_KEY_ARGS \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ServerAliveInterval=15 \
        -o ServerAliveCountMax=2 \
        -o ExitOnForwardFailure=yes \
        -o ConnectTimeout=10 \
        -T -n \
        ${SSH_USER}@localhost.run 2>&1 | while read line; do
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
