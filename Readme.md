# Dvoretskii Bot

## Сервисы

| Сервис | Описание |
|--------|----------|
| `bot` | Telegram бот (Python) |
| `web` | Mini App (React + Vite, порт 5173) |
| `telegram-api` | Локальный Telegram Bot API |
| `caddy` | HTTPS reverse proxy (Let's Encrypt) — только прод |
| `localhost.run` | HTTPS туннель — только dev |
| `fluentbit` | Логирование в Yandex Cloud — только прод |

## Быстрый старт

```bash
cp example.env .env
# заполни .env
```

### Dev (локальная разработка)
```bash
make dev                              # запустить web + bore, покажет URL
make logs-dev                         # логи
```

Для корректной работы HTTPS туннеля через localhost.run для тестирования миниаппы нужно включить чек "Enable host networking" для Docker Desktop (актуально для Windows)

### Prod
```bash
make prod         # запустить
make logs         # логи
```

### Остановить
```bash
make down
```

## Переменные окружения

```bash
# Обязательные
TELEGRAM_BOT_TOKEN=     # от BotFather
TELEGRAM_API_ID=        # my.telegram.org
TELEGRAM_API_HASH=      # my.telegram.org

# Prod (Caddy)
DOMAIN=                 # tg.example.com
ACME_EMAIL=             # email@example.com
```

## Без make

```bash
# Dev
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Prod
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
