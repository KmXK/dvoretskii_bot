# Получение Let's Encrypt сертификата

## Предварительные требования

1. У вас должен быть домен, указывающий на ваш сервер (A запись)
2. Порты 80 и 443 должны быть открыты и доступны из интернета
3. Nginx должен быть запущен в режиме `prod`

## Шаг 1: Настройка переменных окружения

В `.env` файле или `docker-compose.yml` установите:

```env
NGINX_MODE=prod
SSL_DOMAIN=your-domain.com
```

## Шаг 2: Запустите nginx (временно без сертификата)

```bash
docker compose up -d nginx
```

Nginx создаст самоподписанный сертификат как fallback.

## Шаг 3: Получите сертификат через certbot

**Важно:** Перед получением нового сертификата остановите фоновый certbot контейнер:

```bash
docker compose stop certbot
```

### Вариант A: Используя certbot контейнер (рекомендуется)

```bash
docker compose run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email your-email@example.com \
  --agree-tos \
  --no-eff-email \
  -d your-domain.com
```

**После получения сертификата** запустите фоновый certbot обратно:

```bash
docker compose up -d certbot
```

### Вариант B: Используя certbot на хосте

```bash
# Установите certbot
sudo apt-get update
sudo apt-get install certbot

# Получите сертификат
sudo certbot certonly --webroot \
  -w /var/lib/docker/volumes/dvoretskii_bot_certbot-www/_data \
  -d your-domain.com \
  --email your-email@example.com \
  --agree-tos \
  --no-eff-email
```

## Шаг 4: Перезапустите nginx

После получения сертификата:

```bash
docker compose restart nginx
```

Nginx автоматически обнаружит сертификат и переключится на prod конфигурацию.

**Проверьте логи nginx**, чтобы убедиться, что используется Let's Encrypt сертификат:

```bash
docker compose logs nginx | grep -i "certificate\|ssl"
```

Должно быть сообщение: `Using Let's Encrypt certificate for your-domain.com`

## Шаг 5: Проверка

```bash
# Проверьте сертификат
curl -vI https://your-domain.com

# Или откройте в браузере
# https://your-domain.com
```

## Автоматическое обновление

Certbot контейнер автоматически обновляет сертификаты каждые 12 часов. Сертификаты Let's Encrypt действительны 90 дней.

## Отладка

Если что-то не работает:

1. Проверьте логи nginx:
```bash
docker compose logs nginx
```

2. Проверьте наличие сертификата:
```bash
docker compose exec nginx ls -la /etc/letsencrypt/live/${SSL_DOMAIN}/
```

3. Проверьте, что домен указывает на ваш сервер:
```bash
dig your-domain.com
```

4. Проверьте доступность ACME challenge пути:
```bash
# Создайте тестовый файл
docker compose exec nginx sh -c 'echo "test" > /var/www/certbot/test.txt'

# Проверьте доступность
curl http://your-domain.com/.well-known/acme-challenge/test.txt
```

5. Проверьте, что nginx в prod режиме:
```bash
docker compose exec nginx env | grep NGINX_MODE
```

6. Проверьте логи certbot при получении сертификата:
```bash
docker compose logs certbot
```

7. Если получаете ошибку "No renewals were attempted", убедитесь что:
   - Остановили фоновый certbot: `docker compose stop certbot`
   - Используете `certonly`, а не `renew`
   - Домен правильно настроен в DNS
   - Порты 80 и 443 открыты

