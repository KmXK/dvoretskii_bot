#!/bin/sh
# Запускает bore и записывает URL в файл

/bore local 5173 --to bore.pub 2>&1 | while read line; do
    echo "$line"
    # Парсим URL из вывода bore
    if echo "$line" | grep -q "bore.pub:"; then
        URL=$(echo "$line" | grep -oE 'bore\.pub:[0-9]+')
        echo "https://$URL" > /shared/tunnel_url
        echo "=== URL записан: https://$URL ==="
    fi
done

