# Работа с ИИ

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                         Handler                                 │
│  (ai_handler, pasha_handler, ...)                               │
│                                                                 │
│  register_ai_handler("name", ai_call)                           │
│  execute_ai_request(context, text, ai_call, "name")             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │     ai_context.py       │
              │                         │
              │  build_reply_context()  │──── Telethon: собирает
              │  execute_ai_request()   │     цепочку реплаев
              │  register/get_ai_handler│
              └────────────┬────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   AI-провайдеры (ai.py): Yandex, DeepSeek, OpenRouter
         │                 │                 │
         ▼                 ▼                 ▼
┌────────────────────────────────────────────────────┐
│              AiRelatedMessageHandler                │
│                                                     │
│  Ловит реплаи на сообщения бота, определяет         │
│  провайдера по полю handler в ai_messages,           │
│  продолжает диалог через тот же AI                   │
└────────────────────────────────────────────────────┘
```

## Провайдеры

Определены в `steward/helpers/ai.py`. Каждый провайдер — функция, которая принимает `user_id`, `messages` и `system_prompt`, возвращает строку ответа.

| Провайдер | Функция | Async | Примечание |
|---|---|---|---|
| **Yandex GPT** | `make_yandex_ai_query` | да | Самый дешёвый, используй по умолчанию |
| **OpenRouter** | `make_openrouter_query` | да | Любые модели, ходит через `DOWNLOAD_PROXY` |
| **DeepSeek** | `make_deepseek_query` | нет | Принимает `text` вместо `messages`, не поддерживает контекст реплаев |

Доступные модели и env-ключи — см. классы `YandexModelTypes`, `OpenRouterModel` в `ai.py`.

## Формат сообщений

Yandex и OpenRouter принимают `messages: list[tuple[str, str]]` — список кортежей `(role, text)`:

```python
messages = [
    ("user", "Привет"),
    ("assistant", "Здарова"),
    ("user", "Как дела?"),
]
```

## Промпты

Лежат в `prompts/*.txt`. Загружаются при старте через `get_prompt()` в `ai.py` как константы модуля.

Чтобы добавить новый: создай файл в `prompts/` и добавь в `ai.py`:

```python
MY_PROMPT = get_prompt("имя_файла")
```

## Контекст реплаев

`execute_ai_request` автоматически собирает историю диалога из цепочки реплаев в чате.

### Как это работает

1. `build_reply_context()` берёт текущее сообщение и идёт по цепочке `reply_to` через Telethon
2. Для каждого сообщения определяет роль: от бота — `assistant`, иначе — `user`
3. Если прямого реплая нет, ищет связь через `db.ai_messages` (маппинг ответ бота → исходное сообщение)
4. Собранный контекст передаётся в AI-провайдер

### Хранение в БД

После ответа бота в `db.ai_messages` сохраняется `AiMessage` (`timestamp`, `message_id`, `handler`). Максимум 1000 записей, старые вытесняются.

## Как написать новый AI-хендлер

1. Создай промпт в `prompts/`, загрузи в `ai.py`
2. В хендлере вызови `register_ai_handler` с именем и callable — это включит продолжение диалога через реплаи
3. В методе `chat` вызови `execute_ai_request` с нужным провайдером, промптом и тем же именем
4. Зарегистрируй хендлер в `main.py`

`execute_ai_request` берёт на себя: сборку контекста, вызов AI, отправку ответа, сохранение в БД.

Референсные примеры: `ai_handler.py` (OpenRouter), `pasha_handler.py` (Yandex).

## Rate limiting

Все провайдеры ограничены через `check_limit` из `steward/helpers/limiter.py`. При превышении бросается `BucketFullException`, бот отвечает "Слишком много запросов".
