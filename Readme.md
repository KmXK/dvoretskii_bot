## sidecars

-   [Telegram API](https://github.com/tdlib/telegram-bot-api)
-   [cloudflare bypasser](https://github.com/KmXK/cloudflare-bypass)
    just clone repo and run docker ([docker here](https://docs.docker.com/engine/install/ubuntu/))

## Как запустить проект локально

-   Установите Python 3.12+ и `pip`.
-   Установите зависимости: `python -m pip install -r requirements.txt`
-   Создайте файл окружения `.env` (можно скопировать `example.env`) и заполните значения:
    -   `TELEGRAM_BOT_TOKEN` — токен бота от BotFather
    -   `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — значения из [my.telegram.org](https://my.telegram.org/)
    -   при необходимости добавьте `TELEGRAM_API_HOST`, если используете локальный сервер Telegram API
-   Подготовьте базу данных:
    -   добавьте файл `db.json`
-   Запустите бота командой `python main.py`
-   Для остановки бота завершите процесс командой `Ctrl+C` или через `Stop-Process -Id <pid>` в PowerShell.
