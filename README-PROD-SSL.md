# Настройка продакшена с Let's Encrypt сертификатом

## Быстрый старт

1. **Установите переменные окружения** в `.env`:
```env
NGINX_MODE=prod
SSL_DOMAIN=your-domain.com
WEB_APP_URL=https://your-domain.com
```

2. **Пересоберите nginx**:
```bash
docker-compose build nginx
docker-compose up -d nginx
```

3. **Получите сертификат** (см. `nginx/GET-CERTIFICATE.md`):
```bash
docker-compose run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email your-email@example.com \
  --agree-tos \
  --no-eff-email \
  -d your-domain.com
```

4. **Перезапустите nginx**:
```bash
docker-compose restart nginx
```

## Режимы работы

### Dev режим (по умолчанию)
- Использует самоподписанный сертификат
- Подходит для локальной разработки
- `NGINX_MODE=dev` или не установлено

### Prod режим
- Использует Let's Encrypt сертификат
- Требует реальный домен
- `NGINX_MODE=prod`

## Переключение между режимами

1. Измените `NGINX_MODE` в `.env` или `docker-compose.yml`
2. Пересоберите и перезапустите:
```bash
docker-compose build nginx
docker-compose up -d nginx
```

## Проверка

```bash
# Проверьте сертификат
openssl s_client -connect your-domain.com:443 -servername your-domain.com

# Или через curl
curl -vI https://your-domain.com
```

## Автоматическое обновление сертификатов

Certbot контейнер автоматически обновляет сертификаты. Он запускается вместе с docker-compose и проверяет сертификаты каждые 12 часов.

## Troubleshooting

### Сертификат не найден
- Убедитесь, что домен указывает на ваш сервер
- Проверьте, что порты 80 и 443 открыты
- Проверьте логи: `docker-compose logs nginx`

### 502 Bad Gateway
- Проверьте, что web контейнер запущен: `docker-compose ps`
- Проверьте логи web: `docker-compose logs web`

### Сертификат не обновляется
- Проверьте логи certbot: `docker-compose logs certbot`
- Запустите обновление вручную:
```bash
docker-compose run --rm certbot renew
```

