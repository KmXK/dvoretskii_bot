# Контекст для разработки Web App (Telegram Mini App)

### Telegram Web App SDK

В `index.html` подключён оригинальный скрипт Telegram:

```html
<meta name="telegram-web-app" content="true" />
<script src="https://telegram.org/js/telegram-web-app.js"></script>
```

Также установлен npm-пакет `@twa-dev/sdk` — его можно использовать вместо `window.Telegram.WebApp`:

```jsx
import WebApp from '@twa-dev/sdk';

WebApp.ready();
WebApp.expand();
WebApp.MainButton.setText('Готово').show();
```

## Стек бэкенда (steward/)

| Технология                | Назначение                     |
| ------------------------- | ------------------------------ |
| python-telegram-bot       | Telegram Bot API (НЕ aiogram)  |
| Telethon                  | Операции с каналами/форвардами |
| dacite + dataclasses      | Модели данных                  |
| JsonFileStorage (db.json) | Хранилище данных               |

### Паттерн обработчика (Handler)

Базовый класс `Handler` с методами `chat()`, `callback()`, `reaction()` — каждый возвращает `bool`. Первый вернувший `True` останавливает цепочку.

```python
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler

@CommandHandler("mycommand", only_admin=True)
class MyHandler(Handler):
    async def chat(self, context):
        # context.message, context.bot, context.repository, context.client
        await context.message.reply_text("OK")
        return True

    def help(self):
        return "/mycommand - описание"
```

Регистрация в `main.py` → `get_handlers()` — порядок важен.

### Контексты бота

```python
@dataclass
class BotContext:
    repository: Repository
    bot: ExtBot[None]
    client: TelegramClient

class ChatBotContext(BotActionContext):    # message: Message
class CallbackBotContext(BotActionContext): # callback_query: CallbackQuery
class ReactionBotContext(BotActionContext): # message_reaction: MessageReactionUpdated
class DelayedActionContext(BotContext):     # для фоновых задач
```

### Хранилище данных

- `Repository` оборачивает `JsonFileStorage("db.json")`
- `repository.db` — экземпляр `Database` (dataclass со всеми коллекциями)
- Сохранение: `await repository.save()`
- Все коллекции — `list[Model]` или `dict`, мутируются напрямую

Основные коллекции (`Database`):

```
admin_ids, users, chats, rules, rewards, user_rewards,
todo_items, bills, payments, birthdays, banned_users,
delayed_actions, channel_subscriptions, feature_requests, ...
```

## Связь бота и Web App

### Как бот открывает Mini App

Файл `steward/helpers/webapp.py`:

1. **В личных сообщениях** — кнопка с `WebAppInfo(url=WEB_APP_URL)` (открывает внутри Telegram)
2. **В группах** — deep link `https://t.me/{bot_username}/{app_name}?startapp={chat_id}`
3. **Inline-режим** — кнопка `InlineQueryResultsButton` с `WebAppInfo`

### Переменные окружения для Mini App

| Переменная           | Описание                    | Пример                |
| -------------------- | --------------------------- | --------------------- |
| `WEB_APP_URL`        | Прямой HTTPS URL приложения | `https://example.com` |
| `WEB_APP_SHORT_NAME` | Имя Mini App в BotFather    | `dvoretskiy_webapp`   |
| `DOMAIN`             | Домен для Caddy (prod)      | `example.com`         |

### Коммуникация бот ↔ webapp

На стороне бота работает **aiohttp API-сервер** (`steward/api/server.py`), обслуживающий REST API и WebSocket:

**REST API эндпоинты:**
- `GET /api/army` — список армейских таймеров
- `GET /api/todos`, `PATCH /api/todos/{id}` — todo-лист
- `GET /api/feature-requests`, `POST /api/feature-requests`, `PATCH /api/feature-requests/{id}` — фича-реквесты
- `GET /api/profile/{user_id}`, `GET /api/profile/{user_id}/history` — профиль и статистика
- `GET /api/poker/stats/{user_id}` — покерная статистика
- `GET /api/user/{user_id}/chats` — чаты пользователя
- `POST /api/poker/invite`, `POST /api/poker/invite/update`, `POST /api/poker/invite/delete` — покерные приглашения
- `GET /api/exchange?from=USD&to=BYN&amount=1` — конвертация валют (Coinbase / Binance)
- `POST /api/translate` — перевод текста (Yandex Translate), body: `{text, to, from?}`
- `GET /api/timezone?query=...` — текущее время по городу/смещению
- `GET /api/timezone/cities` — список поддерживаемых городов
- `GET /api/reminders/{user_id}` — список напоминаний (active + completed)
- `POST /api/reminders` — создать напоминание, body: `{user_id, chat_id, time, text, repeat?, days?}`
- `DELETE /api/reminders/{id}?user_id=...` — удалить напоминание
- `PATCH /api/reminders/{id}` — изменить текст, body: `{user_id, text}`
- `GET /api/birthdays?chat_id=...` — список дней рождения
- `POST /api/birthdays` — добавить/обновить, body: `{chat_id, name, day, month}`
- `DELETE /api/birthdays` — удалить, body: `{chat_id, name}`
- `GET /api/chat-stats?chat_id=...&period=day&scope=chat&top=15` — статистика чата (лидерборды)

**WebSocket:**
- `GET /ws/poker` — WebSocket для покерных комнат в реальном времени
  - При разрыве WS (сворачивание приложения и т.д.) игрок не удаляется из комнаты сразу — действует grace period 60 сек
  - Во время grace period: auto-fold если ход игрока, пауза игры для bot-only комнат
  - При реконнекте в пределах grace period: восстановление соединения, снятие sitting_out, возобновление игры
  - Автоматическое увеличение блайндов: включено по умолчанию, интервал 1–30 мин (default 5). Уровни: 1x, 1.5x, 2x, 3x, 5x, 7.5x, 10x, 15x, 20x, 30x, 50x, 100x от базовых блайндов. При увеличении broadcast `blinds_increased`. Состояние сбрасывается при окончании игры
  - Объяснение результатов (showdown): кнопка «Почему?» в блоке результатов раскрывает подробности — описание руки каждого игрока (`description` из `_hand_description`), лучшие 5 карт, сравнение комбинаций и причина победы/поражения

**Казино (клиентская сторона):**
- Баланс обезьянок и дневной бонус хранятся в `localStorage` (ключ: `casino_{userId}`)
- Логика слот-машины полностью на клиенте
- Планируется миграция на серверное хранение баланса через API

Валидация `initData` из Telegram пока не реализована.

## Инфраструктура

### Docker Compose

**Dev** (`docker-compose.yml` + `docker-compose.dev.yml`):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

- `web` — Vite dev-сервер с hot reload (watch: sync `web/src → /app/src`)
- `localhost-run` — SSH-туннель для HTTPS URL (записывает URL в `/shared/url`)
- `bot` — ждёт туннель, читает URL → устанавливает `WEB_APP_URL`

**Prod** (`docker-compose.yml` + `docker-compose.prod.yml`):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

- `caddy` — reverse proxy с автоматическим TLS (Let's Encrypt)
- `WEB_APP_URL=https://${DOMAIN}`

### Сеть

Все сервисы в одной Docker-сети `bot`. Web-приложение доступно внутри сети как `web:5173`.

Caddy маршрутизация:

- `${DOMAIN}` → `web:5173` (Mini App)
- `grafana.${DOMAIN}` → `grafana:3000` (мониторинг)

## Модели данных (для API)

Все модели — Python dataclasses в `steward/data/models/`. Ключевые для Mini App:

```python
@dataclass
class User:
    id: int
    username: str

@dataclass
class Reward:
    id: int
    name: str
    emoji: str
    description: str
    custom_emoji_id: str

@dataclass
class UserReward:
    user_id: int
    reward_id: int

@dataclass
class TodoItem:
    id: int
    chat_id: int
    text: str
    is_done: bool

@dataclass
class Birthday:
    name: str
    day: int
    month: int
    chat_id: int

@dataclass
class Bill:
    id: int
    name: str
    file_id: str

@dataclass
class Chat:
    id: int
    name: str
```

## Соглашения по коду

### Python (бэкенд)

- Не писать лишние комментарии — приоритет на чистый код
- Все обработчики наследуют `Handler`, используют `@CommandHandler` декоратор
- Админские команды: `only_admin=True`
- Сохранение данных: мутация `repository.db.*` → `await repository.save()`
- Полиморфная сериализация через `@class_mark` для `DelayedAction`/`Generator`

### JavaScript/React (фронтенд)

- JSX (не TypeScript)
- Функциональные компоненты + хуки (`useState`, `useEffect`, `useRef`)
- Tailwind CSS для стилей (utility-first, никаких отдельных CSS-файлов для компонентов)
- Компоненты в `web/src/components/`, страницы в `web/src/pages/`

## Стек UI-библиотек

| Библиотека         | Назначение                                                         |
| ------------------ | ------------------------------------------------------------------ |
| **Tailwind CSS**   | Utility-first CSS — весь стиль через классы в JSX                  |
| **Radix UI**       | Headless UI-примитивы (Dialog, Tabs, DropdownMenu, Tooltip и т.д.) |
| **Framer Motion**  | Анимации: переходы экранов, казино-механики, микроинтерактив       |
| **React Router**   | Клиентский роутинг между экранами                                  |
| **Recharts**       | Графики и диаграммы (BarChart, LineChart, PieChart)                |
| **TanStack Table** | Headless таблицы: сортировка, фильтрация, пагинация                |

### Как использовать стек

**Tailwind** — основной способ стилизации:

```jsx
<div className='bg-zinc-900 rounded-xl p-4 hover:bg-zinc-800 transition-colors'>
    <h2 className='text-white text-lg font-bold'>Title</h2>
    <p className='text-zinc-400 text-sm'>Secondary text</p>
</div>
```

**Radix UI** — логика + Tailwind стили:

```jsx
import * as Dialog from '@radix-ui/react-dialog';

<Dialog.Root>
    <Dialog.Trigger className='bg-green-500 text-black px-4 py-2 rounded-full font-semibold'>Open</Dialog.Trigger>
    <Dialog.Portal>
        <Dialog.Overlay className='fixed inset-0 bg-black/60' />
        <Dialog.Content className='fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-zinc-900 rounded-xl p-6'>
            <Dialog.Title className='text-white text-lg font-bold'>Modal</Dialog.Title>
        </Dialog.Content>
    </Dialog.Portal>
</Dialog.Root>;
```

**Framer Motion** — анимации:

```jsx
import { motion } from 'framer-motion';

<motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -20 }}
    transition={{ duration: 0.3 }}
    className='bg-zinc-800 rounded-xl p-4'
>
    Animated content
</motion.div>;
```

### Структура фронтенда

```
web/src/
├── main.jsx              # Точка входа
├── App.jsx               # Router + Layout
├── index.css             # Tailwind directives + глобальные стили + casino-анимации
├── components/           # Переиспользуемые компоненты
│   ├── NavBar.jsx
│   └── BackButton.jsx
├── context/
│   └── TelegramContext.jsx  # Telegram WebApp SDK контекст
└── pages/                # Страницы (по маршрутам)
    ├── HomePage.jsx
    ├── ProfilePage.jsx
    ├── CasinoPage.jsx    # Хаб казино (баланс 🐵, бонус, карточки игр, встроенный слот)
    ├── PokerPage.jsx      # Покерное лобби + игра (WebSocket)
    ├── FeaturesPage.jsx
    ├── ArmyPage.jsx
    ├── TodoPage.jsx
    ├── ToolsPage.jsx      # Утилиты: конвертация валют, перевод текста, часовые пояса
    ├── RemindersPage.jsx  # CRUD напоминаний (привязка к чату)
    ├── BirthdaysPage.jsx  # CRUD дней рождения (привязка к чату)
    ├── StatsPage.jsx      # Статистика чатов (лидерборды по метрикам)
    ├── ChartsPage.jsx
    ├── TablePage.jsx
    └── NotFoundPage.jsx
```

### Казино-раздел

CasinoPage работает как хаб с двумя view-состояниями:
- **hub** — баланс обезьянок, кнопка дневного бонуса, сетка карточек игр
- **slots** — встроенная игра «Однорукий бандит» с кнопкой «Назад»

Валюта: **обезьянки** 🐵 (хранение в localStorage).
Подробная документация по экономике: `docs/casino_economy.md`

### Стиль UI — ориентир Spotify

- Тёмная тема как основа: `bg-zinc-950` / `bg-zinc-900` / `bg-zinc-800`
- Акцентный зелёный (`green-500` = `#22c55e`) для ключевых действий
- Белый текст (`text-white`), приглушённый серый (`text-zinc-400`) для вторичного
- Скруглённые карточки (`rounded-xl`), чистые плоские поверхности
- Крупная типографика для заголовков (`text-2xl font-bold`), компактная для списков
- Плавные анимации через Framer Motion и `transition-*` Tailwind-утилиты
- Минимализм: много воздуха, нет лишних рамок и декора
- Мобильное окружение (Telegram) — `user-scalable=no`, `touch-action: none`
- Адаптивность для мобильных экранов обязательна

## Полезные ссылки

- [Telegram Mini Apps Docs](https://core.telegram.org/bots/webapps)
- [@twa-dev/sdk](https://github.com/twa-dev/sdk)
- [Tailwind CSS Docs](https://tailwindcss.com/docs)
- [Radix UI Docs](https://www.radix-ui.com/primitives/docs)
- [Framer Motion Docs](https://motion.dev/docs/react-quick-start)
- [React Router Docs](https://reactrouter.com/)
- [Recharts Docs](https://recharts.org/)
- [TanStack Table Docs](https://tanstack.com/table)
- [python-telegram-bot Docs](https://docs.python-telegram-bot.org/)
- [Vite Docs](https://vite.dev/)
