FROM nginx:alpine

# Устанавливаем openssl для генерации сертификата
RUN apk add --no-cache openssl

# Создаем директорию для SSL
RUN mkdir -p /etc/nginx/ssl

# Генерируем самоподписанный сертификат прямо в образе
RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/key.pem \
    -out /etc/nginx/ssl/cert.pem \
    -subj "/C=RU/ST=State/L=City/O=Organization/CN=localhost"

# Для разработки используем готовый конфиг
COPY nginx-dev.conf /etc/nginx/conf.d/default.conf

CMD ["nginx", "-g", "daemon off;"]

