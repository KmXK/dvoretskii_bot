# Как добавить фичу

Все фичи — наследники `Feature` из `steward/framework/`. Один Feature = одна команда `/x` + связанные с ней callback'и, реакции, сессии. Цель — нулевой бойлерплейт: только описание подкоманд и обработчиков.

## Минимальный пример

```python
# steward/features/foo.py
from steward.framework import Feature, FeatureContext, collection, subcommand


class FooFeature(Feature):
    command = "foo"
    description = "Управление foo"

    items = collection("foo_items")

    @subcommand("", description="Список")
    async def list_(self, ctx: FeatureContext):
        for item in self.items:
            await ctx.reply(str(item))

    @subcommand("add <text:rest>", description="Добавить", catchall=True)
    async def add(self, ctx: FeatureContext, text: str):
        self.items.add(FooItem(text=text))
        await self.items.save()
        await ctx.reply("Добавлено")
```

В `steward/features/registry.py` добавь класс в bucket:

```python
COMMANDS << [..., FooFeature, ...]
```

## Атрибуты класса

| Атрибут | Дефолт | Назначение |
|---|---|---|
| `command` | `None` | имя команды без `/`. `None` — Reactor (без команды) |
| `aliases` | `()` | алиасы: `aliases = ("featurerequest",)` для `/fr` |
| `description` | `""` | одна строка для `/help` и AI-router |
| `only_admin` | `False` | вся фича только для админов |
| `excluded_from_ai_router` | `False` | не показывать в `/ai`-роутинге |
| `help_examples` | `[]` | примеры фразочек для AI prompt |
| `custom_help` / `custom_prompt` | `None` | если не нравится автогенерация |

`help()` и `prompt()` собираются автоматически из `command + description + описаний подкоманд`.

## Подкоманды (subcommand DSL)

```python
@subcommand("",                      description="без аргументов")
@subcommand("list",                  description="литерал")
@subcommand("punishment today",      description="многословный литерал")
@subcommand("<n:int>",               description="одно число")
@subcommand("done <id:int>",         description="литерал + параметр")
@subcommand("add <coeff:int> <title:rest>", description="несколько параметров")
@subcommand("<id:int> priority <p:int>", description="литерал в середине")
@subcommand("<text:rest>", catchall=True)
@subcommand(re.compile(r"^complex .*"))   # escape hatch для сложного regex
```

Типы: `int`, `float`, `str` (одно слово), `rest` (всё до конца, только последний), `literal[a|b|c]`.

Опции: `description=` (для help), `admin=True` (per-subcommand), `catchall=True` (последняя в очереди матчинга).

## Repository через Collection

```python
class FooFeature(Feature):
    items = collection("foo_items")            # ListCollection[FooItem]
    admin_ids = collection("admin_ids")        # SetCollection[int]
    cache = collection("data_offsets")         # DictCollection[str, float]
```

Тип определяется по runtime-типу поля `Database`.

**ListCollection** (для list[Model] с `id`):
- `.all()`, `.filter(**kw)`, `.find_by(**kw)`, `.find_one(predicate)`
- `.add(item)` — авто-присваивает `id`
- `.remove(item)`, `.remove_where(**kw)`, `.replace_all(items)`, `.next_id()`, `.sort_by(key)`
- `await .save()`

**SetCollection** (для set[primitive]):
- `.add(x) -> bool`, `.remove(x) -> bool`, `.contains(x)`, `x in coll`
- `.add_many([...])`, `.remove_many([...])`
- `await .save()`

**DictCollection** (для dict[K, V]):
- `.get(k)`, `.set(k, v)`, `.pop(k)`, `.contains(k)`
- `.keys()`, `.values()`, `.items()`
- `await .save()`

## Inline‑кнопки и callback‑схемы

Типизированный callback (предпочтительно):

```python
@on_callback("todo:reward",
             schema="<answer:literal[yes|no]>|<todo_id:int>|<initiator:int>",
             access=INITIATOR_ONLY)
async def on_reward(self, ctx, answer, todo_id, initiator):
    if answer == "no":
        await ctx.delete_or_clear_keyboard()
        return
    await self.start_wizard("ask_reward", ctx, todo_id=todo_id)
```

Кнопки строятся через фабрику, привязанную к схеме (типы и имена проверяются на этапе сборки):

```python
cb = self.cb("todo:reward")
kb = Keyboard.row(
    cb.button("Да",  answer="yes", todo_id=5, initiator=ctx.user_id),
    cb.button("Нет", answer="no",  todo_id=5, initiator=ctx.user_id),
)
await ctx.reply("Засчитать?", keyboard=kb)
```

Имя callback'а — `feature:action`. Поля схемы — через `|`.

### Access policy

`@on_callback` и `@wizard` принимают параметр `access: AccessPolicy` (по умолчанию `OPEN` — кнопкой может пользоваться любой). Доступные политики:

- `OPEN` — без ограничений.
- `INITIATOR_ONLY` (или `initiator_only("field")` для другого имени поля) — кнопка работает только у юзера с `ctx.user_id == kwargs["initiator"]`. Поле должно быть в схеме и заполняться при создании кнопки.
- `resource_author("field", admin_bypass=False)` — доступ только у автора ресурса. Фреймворк парсит `kwargs[field]`, вызывает `Feature.resolve_owner(field, value) -> int | None` (его нужно переопределить в фиче) и сравнивает с `ctx.user_id`.

Пример (`/bills`):
```python
@on_callback("bills:edit", schema="<bill_id:int>",
             access=resource_author("bill_id", admin_bypass=True))
async def on_edit(self, ctx, bill_id): ...

def resolve_owner(self, field: str, value):
    if field == "bill_id":
        bill = self.repository.get_bill_v2(int(value))
        person = bill and self.repository.get_bill_person(bill.author_person_id)
        return person.telegram_id if person and person.telegram_id else None
    return None
```

Если проверка не прошла, фреймворк сам шлёт `toast` (или `reply` для не-callback контекста) и не вызывает обработчик.

## Pagination

**Декоратор `@paginated` + метод `Feature.paginate(ctx, name, metadata=)`** — единый API. Фреймворк сам регистрирует callback под капотом.

```python
class TodoFeature(Feature):
    @subcommand("")
    async def list_(self, ctx):
        await self.paginate(ctx, "todos", metadata=str(ctx.chat_id))

    @paginated("todos", per_page=10, header="События")
    def todos_page(self, ctx, metadata: str):
        chat_id = int(metadata)
        items = [t for t in self.todos if t.chat_id == chat_id and not t.is_done]
        render = lambda batch: format_lined_list([(t.id, t.text) for t in batch])
        return items, render
```

Функция возвращает `(items, render)` или `(items, render, extra_keyboard)` — если нужны фильтры/доп.кнопки под пагинацией.

Опции `@paginated`: `per_page=10`, `header=""`, `empty_text="Список пуст"`, `parse_mode="markdown"|"HTML"|None`.

Дополнительные кнопки можно построить через `self.page_button(name, label, metadata=, page=0)` — например, для фильтров:

```python
@paginated("frs", per_page=15, header="Фича-реквесты")
def frs_page(self, ctx, metadata: str):
    items = sorted(filter(_filter_for(metadata), self.feature_requests.all()), key=...)
    render = lambda batch: format_lined_list([(fr.id, fmt(fr)) for fr in batch])
    extra = Keyboard.row(*[
        self.page_button("frs", label, metadata=str(f.value), page=0)
        for label, f in _OPTIONS if f != _Filter(int(metadata))
    ])
    return items, render, extra
```

## Wizard (декларативная сессия)

Всё, что состоит из «спросить значения → сделать что-то» — декларативно через `@wizard`. Активация всегда через `await self.start_wizard("name", ctx, **initial_state)` — фреймворк сам разворачивает первый шаг.

```python
from steward.framework import wizard, ask, ask_message, choice, confirm, step

class FooFeature(Feature):
    @subcommand("done <id:int>")
    async def done(self, ctx, id):
        ...
        await self.start_wizard("ask_reward", ctx, todo_id=id)

    @wizard(
        "ask_reward",
        ask("name", "Название достижения", validator=non_empty),
        ask("emoji", "Эмодзи достижения", validator=extract_emoji),
        ask_message("photo", "Пришли фото",
                    filter=lambda m: bool(m.photo),
                    transform=lambda m: m.photo[-1]),
        choice("kind", "Тип?", [("public", "Публичное"), ("private", "Личное")]),
        confirm("ok", "Сохранить?"),
    )
    async def on_done(self, ctx, name, emoji, photo, kind, ok, todo_id):
        # state = всё что собрали + initial kwargs из start_wizard (todo_id)
        ...
```

### Виды шагов

| Шаг | Что делает |
|---|---|
| `ask(key, q, validator=)` | спрашивает текст; результат — строка после валидации |
| `ask_message(key, q, filter=, transform=, error=)` | ждёт сообщение, удовлетворяющее `filter`; `transform` извлекает что нужно (фото, голос, форвард). `error` — что ответить при невалидном вводе |
| `choice(key, q, options=[(label, value), ...])` | inline-кнопки; результат — выбранное `value` |
| `confirm(key, q)` | сахар над `choice` с Да/Нет → bool |
| `step(key, custom_step_instance)` | подмешать произвольный `Step` (когда нужна сложная нелинейная логика — см. ниже) |

Условные шаги: `ask(..., when=lambda state: bool(state.get("...")))` — выполняется только если предикат истинен. Иначе шаг пропускается.

Динамический вопрос: `ask(key, lambda state: f"...{state['name']}...", ...)`.

### Iteration через рекурсию

Wizard не имеет встроенной петли, но `start_wizard` можно вызывать из `on_done`, передавая обновлённое состояние:

```python
@subcommand("")
async def infinite(self, ctx):
    await self.start_wizard("loop", ctx, repeat=-1, current=0)

@wizard("loop", ask_message("msg", "Пришли сообщение", filter=...))
async def on_done(self, ctx, msg, repeat, current):
    ...
    if repeat == -1 or current + 1 < repeat:
        await self.start_wizard("loop", ctx, repeat=repeat, current=current + 1)
```

## Кастомный Step внутри wizard

Когда нужна нелинейная логика (intermediate buttons, perpetual loop) — пишешь свой `Step` и вкладываешь в wizard через `step("key", _MyStep())`:

```python
from steward.session.step import Step

class _GptStep(Step):
    async def chat(self, context):
        # context — ChatStepContext (= ChatBotContext + session_context)
        # вернуть True чтобы перейти к следующему шагу
        ...

    async def callback(self, context):
        return context.callback_query.data == "stop"

    def stop(self):
        ...

class PashaFeature(Feature):
    @subcommand("")
    async def start(self, ctx):
        await self.start_wizard("chat", ctx)

    @wizard("chat", step("gpt", _GptStep()))
    async def on_done(self, ctx, **state):
        pass
```

`SessionHandlerBase` напрямую больше не нужен — для всех новых сессий используй `start_wizard` + `step()`.

## Reactor — фича без команды

```python
class CurseMetricFeature(Feature):
    curse_words = collection("curse_words")

    @on_message
    async def count(self, ctx) -> bool:
        if ctx.message is None: return False
        ...
        return False  # не блокирует цепочку
```

`@on_message` — на любое входящее сообщение (после command-роутинга, если фича не имеет команды).
`@on_reaction` — на любую реакцию.

Reactor сидит в bucket `EARLY` (мониторы) или `LATE` (fallback'и).

**Несколько `@on_message` / `@on_reaction` в одной фиче:** вызываются в порядке определения в исходнике (Python 3.7+ сохраняет порядок в `__dict__`, фреймворк это уважает). Первый, вернувший `True`, останавливает цепочку — и в рамках фичи, и для глобального диспетчера. Возврат `False`/`None` отдаёт ход следующему хендлеру внутри фичи. Если все вернули `False/None` — `Bot._action()` идёт к следующей фиче.

## on_init — однократный setup

```python
class CurseFeature(Feature):
    @on_init
    async def _setup_digest(self):
        if any(isinstance(a, CursePunishmentDigestDelayedAction)
               for a in self.delayed_actions):
            return
        self.delayed_actions.add(CursePunishmentDigestDelayedAction(...))
        await self.delayed_actions.save()
```

## FeatureContext API

Поля: `update`, `repository`, `bot`, `client`, `metrics`, `message`, `callback_query`, `reaction`.

Shortcuts: `chat_id`, `user_id`, `username`, `is_callback`.

Методы:
- `await ctx.reply(text, keyboard=, html=, markdown=)` — ответить
- `await ctx.edit(text=None, keyboard=)` — редактировать сообщение из callback
- `await ctx.toast(text, alert=False)` — короткий тост в callback
- `await ctx.delete_or_clear_keyboard()` — удалить или хотя бы убрать клаву
- `await ctx.send_to(chat_id, text, ...)` — отправить в произвольный чат

## Регистрация в registry

`steward/features/registry.py`:
- `EARLY` — мониторы и enforcer'ы (бан, тишина, метрики). Срабатывают первыми.
- `COMMANDS` — обычные slash-команды. Порядок не важен.
- `LATE` — `RuleAnswerFeature` и подобные fallback'и.

```python
COMMANDS << [..., FooFeature, ...]
```

Спец-хендлеры (`AiRouterHandler`, `HelpHandler`, `LogsFeature`) добавляются в `main.py`.

## Capability и permission новой фичи

С версии БД 33 (см. `docs/settings.md`) фичи бьются по **capabilities** — группам функций, которые `chat-admin` включает/выключает в каждом чате через `/settings`.

- Добавляй новую фичу в `CAPABILITIES` в `steward/features/registry.py`. Если capability'ы нет смысла — фича всегда работает, ничего не делай (capability = None → bypass).
- `ALWAYS_ON` — список фич, которые игнорируют capability-чек (мониторы, AdminFeature, SettingsFeature, BroadcastFeature и т.п.).
- `feature_slug(cls)` — это `ClassName.removesuffix("Feature").lower()`. Используется для точечного отключения отдельной фичи внутри включённой capability.

Permission — gate на конкретную подкоманду:

```python
@subcommand("done <ids:rest>",
            description="Закрыть FR",
            permission="feature_request.status")
async def cmd_done(self, ctx, ids): ...
```

Логика gating'а (см. `Repository.has_permission`):
- если permission `None` → открыто всем
- если global-admin → всегда `True` (биппас)
- если permission ни в одной роли (`gated_permissions()` пустая) → открыто всем
- иначе нужна роль с этой permission

UI редактирования ролей — `/settings → 🎭 Роли` (global-admin only) или web `/settings`.

## Тесты

```python
from steward.features.foo import FooFeature
from tests.conftest import invoke, make_repository

async def test_add():
    repo = make_repository()
    reply, ok = await invoke(FooFeature, "/foo add hello", repo)
    assert ok
    assert "Добавлено" in reply
    assert len(repo.db.foo_items) == 1
```

Для admin-only подкоманд: `repo.db.admin_ids = {12345}`.

Unit-тесты на DSL/callback parser — `tests/test_framework_*.py`.

## Структура файла фичи

Маленькая фича — один файл `features/foo.py`. Большая (≥400 строк) — пакет:

```
features/foo/
  __init__.py        # class FooFeature(Feature) — все @subcommand/@on_callback/@wizard/@paginated
  pure_functions.py  # бизнес-логика, парсеры, форматирование
  custom_steps.py    # custom Step'ы для @wizard(step("name", _MyStep()))
```

Эталоны:
- `features/admin.py` — минимальный CRUD с SetCollection
- `features/curse.py` — много подкоманд + on_init
- `features/todo.py` — wizard + on_callback + paginated
- `features/me.py` — paginated с extra_keyboard
- `features/feature_request.py` — paginated с фильтр-кнопками через `page_button()`
- `features/multiply.py` — wizard с `ask_message` для голоса
- `features/pasha.py` — wizard со `step()` для perpetual GPT
- `features/subscribe/` — wizard со `step()` для нелинейного потока
- `features/bills/` — большой пакет с pagination + 3 wizard'а

## Что НЕ делать

- **Не наследовать `Handler` напрямую** — используй `Feature`.
- **Не наследовать `SessionHandlerBase`** — используй `@wizard` + `step()` для любой сессионной логики.
- **Не писать `data.split("|")`** — типизированная схема в `@on_callback` всё парсит.
- **Не строить inline-кнопки руками** через `InlineKeyboardMarkup([[InlineKeyboardButton(...)]])` — используй `Keyboard.row(self.cb("name").button("text", **kwargs))`.
- **Не писать `next((x for x in repo.db.X if x.id == y), None)`** — используй `Collection.find_by(id=y)`.
- **Не писать комменты** про то «что делает код» — имена и сигнатуры должны говорить сами за себя.
