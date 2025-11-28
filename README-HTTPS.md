# Настройка HTTPS для Web приложения

Есть несколько способов поднять HTTPS сервер:

## Вариант 1: Vite с HTTPS (Самый простой для разработки) ⭐ РЕКОМЕНДУЕТСЯ

1. Сгенерируйте SSL сертификат:
```bash
cd web
chmod +x generate-ssl.sh
./generate-ssl.sh
```

2. Раскомментируйте строку в `docker-compose.yml` для web сервиса:
```yaml
- VITE_HTTPS=true
```

3. Перезапустите контейнер:
```bash
docker-compose restart web
```

4. Установите `WEB_APP_URL=https://localhost:5173` в `.env` или `docker-compose.yml`

**Внимание:** Браузер будет показывать предупреждение о самоподписанном сертификате. Нажмите "Дополнительно" → "Перейти на localhost".

## Вариант 2: Cloudflare Tunnel (Простой для разработки)

1. Установите Cloudflare Tunnel:
```bash
# Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
```

2. Запустите туннель:
```bash
cloudflared tunnel --url http://localhost:5173
```

3. Используйте полученный HTTPS URL в `WEB_APP_URL`

## Вариант 3: ngrok (Очень простой)

1. Установите ngrok: https://ngrok.com/download
2. Запустите:
```bash
ngrok http 5173
```
3. Используйте полученный HTTPS URL (например, `https://xxxx.ngrok.io`) в `WEB_APP_URL`

## Вариант 4: Nginx с самоподписанным сертификатом

1. Сгенерируйте SSL сертификат:
```bash
cd nginx
chmod +x generate-ssl.sh
./generate-ssl.sh
```

2. Раскомментируйте nginx сервис в `docker-compose.yml`

3. Установите `WEB_APP_URL=https://localhost` (или ваш домен)

## Вариант 5: Nginx с Let's Encrypt (Для продакшена)

1. Убедитесь, что у вас есть домен, указывающий на ваш сервер
2. Установите certbot:
```bash
sudo apt-get update
sudo apt-get install certbot
```

3. Получите сертификат:
```bash
sudo certbot certonly --standalone -d your-domain.com
```

4. Обновите `nginx/nginx.conf` с вашим доменом
5. Раскомментируйте nginx сервис в `docker-compose.yml`

