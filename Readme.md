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

#### Стабильный URL туннеля (опционально, но удобно)

По умолчанию `localhost.run` выдаёт случайный `*.lhr.life` URL при каждом
переподключении — приходится каждый раз делать `/setdomain` в BotFather. Чтобы
URL был стабильным, привяжи персональный SSH-ключ:

```bash
# 1. Сгенерь отдельный ключ под туннель (не используй основной ~/.ssh/id_*)
ssh-keygen -t ed25519 -N "" -f scripts/tunnel-key/id_ed25519 -C "dvoretskii-bot-tunnel"

# 2. Заведи аккаунт на https://admin.localhost.run/ (через email/google) и
#    добавь публичную часть scripts/tunnel-key/id_ed25519.pub в раздел SSH
#    Keys. Важно: ключ должен быть привязан к АККАУНТУ — просто залить .pub
#    в анонимную форму недостаточно, в логах увидишь "authenticated as
#    anonymous user" и URL будет каждый раз новый.

# 3. make dev — в логах localhost-run увидишь свой постоянный URL.
#    Один раз делаешь /setdomain в BotFather — и забываешь.
```

Папка `scripts/tunnel-key/` в gitignore, ключ остаётся локально. Если ключа
нет — `make dev` работает как раньше (анонимный режим, случайный URL).

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
