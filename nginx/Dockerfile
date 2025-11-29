FROM nginx:alpine

# Устанавливаем openssl и envsubst для подстановки переменных
RUN apk add --no-cache openssl gettext

# Создаем директории
RUN mkdir -p /etc/nginx/ssl /var/www/certbot

# Копируем оба конфига
COPY nginx-dev.conf /etc/nginx/templates/nginx-dev.conf.template
COPY nginx-prod.conf /etc/nginx/templates/nginx-prod.conf.template

# По умолчанию используем dev конфиг (можно переопределить через переменную окружения)
ENV NGINX_MODE=dev
ENV SSL_DOMAIN=localhost

# Скрипт для выбора конфига
COPY docker-entrypoint.sh /docker-entrypoint-custom.sh
RUN chmod +x /docker-entrypoint-custom.sh

# Сохраняем оригинальный entrypoint
ENTRYPOINT ["/docker-entrypoint-custom.sh"]
CMD ["nginx", "-g", "daemon off;"]

