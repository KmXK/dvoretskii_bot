# План: фича `/settings` — тонкая настройка бота по чатам + роли

> **Status: implemented (v33)** — реализация в `steward/features/settings.py`, миграция в `Repository._migrate` (32→33), API в `steward/api/settings_routes.py`, UI в `web/src/pages/SettingsPage.jsx`. Документ оставлен как референс архитектуры.

Документ описывает реализацию команды `/settings`, по-чатных тумблеров фич, флага `chat_admin` и глобальной системы ролей с permissions. Самодостаточный — реализатор не должен догадываться о контексте, всё необходимое здесь.

---

## 1. Контекст (как сейчас)

- Каждая фича — наследник `Feature` (`steward/framework/feature.py`). Полный гайд по фреймворку — `FEATURES.md`.
- Фичи регистрируются в `steward/features/registry.py` в трёх buckets: `EARLY` (мониторы/энфорсеры), `COMMANDS` (slash-команды), `LATE` (фоллбеки типа `RuleAnswerFeature`).
- Глобальные админы — `db.admin_ids: set[int]`. Проверка `Repository.is_admin(user_id)` (`steward/data/repository.py:135`).
- Фича может быть admin-only через class-level `only_admin = True` (мапится в `Handler.only_for_admin`). Подкоманды — через `@subcommand(..., admin=True)`.
- Per-feature allowlists уже есть точечно: `DianaFeature.allowed_chats` (`db.diana_allowed_chats: set[int]`). Аналоги: `silenced_chats`, `joke_settings`.
- Чаты пополняются автоматически через `ChatCollectFeature` (`steward/features/chat_collect.py`). Хранятся в `db.chats: list[Chat]`. Пользователи — `db.users: list[User]` c полем `chat_ids`.
- Хендлер `my_chat_member` НЕ подключён. Telegram-апдейт «бота добавили/удалили из чата» сейчас игнорируется.
- Базовый dispatcher — `Bot._action` (`steward/bot/bot.py:250`). Сейчас он зовёт `_validate_admin` перед каждым хендлером и всё.
- `/help` реализован в `HelpFeature` (`steward/features/_special/help.py`). Показывает только admin/non-admin фильтр.
- Web-апп: aiohttp-сервер в `steward/api/server.py`, фронтенд `web/src/` (React + Vite). Auth — Telegram WebApp `init_data`, `session_user_id(request)` (`steward/api/auth.py`).
- БД — JSON-файл, версионируется через `Database.version` (сейчас 30). Миграции — `Repository._migrate` (`steward/data/repository.py`).

---

## 2. Цели

1. Команда `/settings` доступна в любом чате в любое время.
2. По-чатно включать/выключать фичи (gран. — capability-группы с drill-down на отдельные фичи).
3. Глобальный админ создаёт **роли** (произвольные, именованные) с набором **permissions**. Одна permission гейтит конкретные подкоманды/действия фичи. По умолчанию permission открыта всем; как только она оказывается хотя бы в одной роли — её могут использовать только владельцы такой роли (или глобальный админ).
4. Один пользователь может иметь несколько ролей.
5. Внутри чата есть флаг `chat_admin` (не роль): несколько админов на чат разрешено. Они могут менять capability-тоглы и менеджить других chat_admin. Роли (которые permissions) они НЕ создают.
6. При добавлении бота в новый чат: тот, кто добавил, становится `chat_admin`; все capabilities выключены; бот отправляет приветствие с кнопкой «Открыть настройки».
7. Существующие чаты при миграции: все capabilities ВКЛ, никаких `chat_admin` не назначаем (управляют только глобальные админы пока кто-то сам не назначит chat_admin).
8. Скрытые (выключенные) фичи не показываются в `/help` и не попадают в AI-router для этого чата.
9. Те же настройки доступны через web-апп с теми же правами.
10. Глобальные админы (`db.admin_ids`) — supreme, биппасят все три механизма.

---

## 3. Архитектура: три ортогональные оси

| Ось | Кто меняет | Что определяет | Дефолт |
|---|---|---|---|
| **Capability toggle (per chat)** | chat_admin или global_admin | Работает ли фича в этом чате | Существующие чаты: ON. Новые: OFF |
| **chat_admin flag (per chat)** | другой chat_admin или global_admin | Кто рулит настройками этого чата | Тот, кто добавил бота |
| **Permission (global)** | только global_admin | Может ли юзер вызвать конкретную подкоманду | Открыто всем, пока хотя бы одна роль её не требует |

Глобальный админ биппасит все три.

---

## 4. Структуры данных

### 4.1. Новые модели

`steward/data/models/role.py`:
```python
from dataclasses import dataclass, field


@dataclass
class Role:
    id: int
    name: str                       # "Разработчик"
    permissions: set[str] = field(default_factory=set)


@dataclass
class UserRole:
    user_id: int
    role_id: int
```

`steward/data/models/chat_settings.py`:
```python
from dataclasses import dataclass, field


@dataclass
class ChatSettings:
    chat_id: int
    enabled_capabilities: set[str] = field(default_factory=set)
    disabled_features: set[str] = field(default_factory=set)  # фичи внутри включённой capability, точечно выключенные
    chat_admins: set[int] = field(default_factory=set)
    onboarded: bool = False
```

Хранить только отключения внутри включённой capability — компактно. Если capability выключена, `disabled_features` для неё игнорируется.

### 4.2. Расширение `Database`

В `steward/data/models/db.py` добавить поля:
```python
roles: list[Role] = field(default_factory=list)
user_roles: list[UserRole] = field(default_factory=list)
chat_settings: list[ChatSettings] = field(default_factory=list)

version: int = 31   # bump
```

Импортировать `Role`, `UserRole`, `ChatSettings` рядом с другими импортами в `db.py`.

### 4.3. Collections (через фреймворк)

В фичах объявляем как обычно:
```python
roles = collection("roles")               # ListCollection[Role]
user_roles = collection("user_roles")     # ListCollection[UserRole]
chat_settings = collection("chat_settings")  # ListCollection[ChatSettings]
```

---

## 5. Capability mapping

Централизованный реестр в `steward/features/registry.py`. Дополнить файл:

```python
CAPABILITIES: dict[str, set[type]] = {
    "ai":         {AIFeature, AiRelatedFeature, PashaFeature, DianaFeature, TranslateFeature},
    "transcribe": {TranscribeFeature, ShazamFeature, MultiplyFeature, VoiceVideoFeature},
    "rules":      {RuleFeature, RuleAnswerFeature},
    "fun":        {JokeFeature, TarotFeature, FuckFeature, SexFeature, ReactFeature, WatchFeature, EveryoneFeature},
    "trackers":   {ArmyFeature, BillsFeature, BirthdayFeature, TodoFeature, IncidentFeature,
                   RemindFeature, RemindersFeature, MeFeature, RewardFeature, StandsFeature,
                   SubscribeFeature, FeatureRequestFeature},
    "chat_meta":  {IdFeature, MessageInfoFeature, PrettyTimeFeature, TimezoneFeature, HolidaysFeature,
                   ExchangeRateFeature, LinkFeature, LayoutFeature, NewTextFeature, LangFeature},
    "stats":      {StatsFeature, CurseFeature, CurseMetricFeature},
    "downloads":  {DownloadFeature, GoogleDriveFeature},
    "moderation": {BanFeature, BanEnforcerFeature, SilenceFeature, SilenceEnforcerFeature},
}

ALWAYS_ON: set[type] = {
    AdminFeature, SettingsFeature, MiniAppFeature, ChatCollectFeature,
    ReactionCounterFeature, UserMemoryFeature, HighcastCleanupFeature,
    DbFeature, BroadcastFeature,
    # HelpFeature и AiRouterHandler — не в bucket, регистрируются в main.py, всегда работают
}

CAPABILITY_LABELS: dict[str, str] = {
    "ai":         "AI-помощник",
    "transcribe": "Транскрибация",
    "rules":      "Правила-ответы",
    "fun":        "Развлечения",
    "trackers":   "Трекеры",
    "chat_meta":  "Утилиты чата",
    "stats":      "Статистика",
    "downloads":  "Скачивание",
    "moderation": "Модерация",
}
```

Добавить хелперы (туда же):
```python
def capability_of(feature_cls: type) -> str | None:
    for cap, classes in CAPABILITIES.items():
        if feature_cls in classes:
            return cap
    return None

def feature_slug(feature_cls: type) -> str:
    return feature_cls.__name__.removesuffix("Feature").lower()  # FeatureRequestFeature -> "featurerequest"

ALL_CAPABILITIES: set[str] = set(CAPABILITIES.keys())
```

Базовый `Handler` (`steward/handlers/handler.py`) получает:
```python
@property
def capability(self) -> str | None:
    from steward.features.registry import capability_of
    return capability_of(self.__class__)
```

---

## 6. Permissions

### 6.1. Слот в subcommand

В `steward/framework/subcommand.py` добавить в `Subcommand` (dataclass) поле:
```python
permission: str | None = None
```

В декораторе `subcommand(..., permission: str | None = None, ...)` — пробросить.

### 6.2. Резолвер

В `steward/data/repository.py`:
```python
def permissions_of(self, user_id: int) -> set[str]:
    role_ids = {ur.role_id for ur in self.db.user_roles if ur.user_id == user_id}
    out: set[str] = set()
    for r in self.db.roles:
        if r.id in role_ids:
            out |= r.permissions
    return out

def gated_permissions(self) -> set[str]:
    out: set[str] = set()
    for r in self.db.roles:
        out |= r.permissions
    return out

def has_permission(self, user_id: int, perm: str | None) -> bool:
    if perm is None:
        return True
    if self.is_admin(user_id):
        return True
    if perm not in self.gated_permissions():
        return True   # никем не закрыта — открыта всем
    return perm in self.permissions_of(user_id)
```

Кэшировать `gated_permissions()` — пересчёт при `save()` (через `subscribe_on_save`).

### 6.3. Permissions для существующих фич

Помечаем подкоманды **только сейчас в `FeatureRequestFeature`** (`steward/features/feature_request.py`):

```python
@subcommand("<fr_id:int> priority <p:int>", description="Сменить приоритет",
            permission="feature_request.priority")
@subcommand("<fr_id:int> note <text:rest>", description="Добавить примечание",
            permission="feature_request.note")
@subcommand("done <ids:rest>", description="Сменить статус: done",
            permission="feature_request.status")
@subcommand("deny <ids:rest>", description="Сменить статус: deny",
            permission="feature_request.status")
@subcommand("reopen <ids:rest>", description="Сменить статус: reopen",
            permission="feature_request.status")
@subcommand("inprogress <ids:rest>", description="Сменить статус: inprogress",
            permission="feature_request.status")
@subcommand("testing <ids:rest>", description="Сменить статус: testing",
            permission="feature_request.status")
```

Просмотр (`@subcommand("")`, `@subcommand("<fr_id:int>")`, `list`, `like`) и создание FR (catchall) — без `permission`.

Это используется ролью «Разработчик» из миграции (см. §10).

### 6.4. Реестр permissions для UI

Сборка списка известных permissions (для чекбоксов в редакторе роли):
```python
# в SettingsFeature
def known_permissions(self) -> list[str]:
    out: set[str] = set()
    for h in self._all_handlers:
        for sub in getattr(h, "_subcommands", []):
            if sub.permission:
                out.add(sub.permission)
    return sorted(out)
```

`_all_handlers` уже инициализируется в `Bot.__init__` (`steward/bot/bot.py:79`).

---

## 7. Enforcement

### 7.1. В `Bot._action` (steward/bot/bot.py)

Заменить `_validate_admin` на универсальный `_validate_access`:

```python
def _validate_access(self, handler: Handler, ctx: BotActionContext) -> bool:
    if handler.only_for_admin and not self.repository.is_admin(ctx.user_id_or_none()):
        return False
    if handler.__class__ in ALWAYS_ON:
        return True
    chat = ctx.update.effective_chat
    if chat is None or chat.type == "private":
        return True
    cap = handler.capability
    if cap is None:
        return True
    return self.repository.is_capability_enabled(chat.id, handler.__class__)
```

Helper в `Repository`:
```python
def chat_settings_for(self, chat_id: int) -> ChatSettings:
    for s in self.db.chat_settings:
        if s.chat_id == chat_id:
            return s
    s = ChatSettings(chat_id=chat_id)
    self.db.chat_settings.append(s)
    return s

def is_capability_enabled(self, chat_id: int, feature_cls: type) -> bool:
    from steward.features.registry import capability_of, feature_slug
    cap = capability_of(feature_cls)
    if cap is None:
        return True
    s = self.chat_settings_for(chat_id)
    if cap not in s.enabled_capabilities:
        return False
    return feature_slug(feature_cls) not in s.disabled_features

def is_chat_admin(self, user_id: int, chat_id: int) -> bool:
    if self.is_admin(user_id):
        return True
    s = self.chat_settings_for(chat_id)
    return user_id in s.chat_admins
```

### 7.2. Permission-чек в subcommand-диспетчере

В `Feature._dispatch_subcommand` (`steward/framework/feature.py:279`) после существующего `if sub.admin and not ctx.repository.is_admin(...)` блок:

```python
if sub.permission and not ctx.repository.has_permission(ctx.user_id, sub.permission):
    await ctx.reply("Недостаточно прав для этого действия.")
    return True
```

### 7.3. Поведение при выключенной capability

- Slash-команда (`Feature.command is not None`, в `chat()` определена `validate_command_msg`): отвечать `«Функция выключена в этом чате. /settings»`. Это происходит в `Bot._action` через флаг — если capability выключена И это команда (а не reactor) — ответ «выключено».
- Reactor (`@on_message`, `@on_reaction`): молча `return False`.

Чтобы различать: в `Bot._action` смотреть на `update.message.text` — если начинается с `/<handler.command>` (и фича выключена) → ответ; иначе молчим.

---

## 8. `/help` и AI-router — фильтрация по чату

### 8.1. `HelpFeature`

Файл `steward/features/_special/help.py`. Передаём `repository` в `_build_overview`:

```python
def _is_visible(handler, repo, user_id, chat_id) -> bool:
    if handler.__class__ in ALWAYS_ON:
        return True
    cap = handler.capability
    if cap is None:
        return True
    return repo.is_capability_enabled(chat_id, handler.__class__)

def _visible_subcommands(handler, repo, user_id):
    return [s for s in getattr(handler, "_subcommands", [])
            if repo.has_permission(user_id, s.permission)]
```

Если у фичи после фильтрации subcommands пусто (а command есть) — не показывать вообще.

Private chat — всё видно (capability считаются включёнными в личке).

`/help <command>`: если фича скрыта — отвечаем `«Команда не найдена»`, как сейчас для admin-only.

### 8.2. AI-router

Найти `AiRouterHandler` (упомянут в `FEATURES.md` как регистрируемый в `main.py`). Где он собирает `prompt()` — отфильтровать ровно теми же двумя проверками. В реализации скорее всего обход `self._all_handlers` — туда добавить проверки `is_capability_enabled` и `has_permission`.

---

## 9. UI `/settings`

### 9.1. Корневое сообщение

```
⚙ Настройки — {chat_name}

Включено: 5/9 функций
Вы: chat-admin                 ← или "пользователь" / "global-admin"

[ 📦 Функции ]
[ 👥 Чат-админы ]
[ 🎭 Роли ]                    ← только если ctx.user — global_admin
[ ℹ Помощь ]
```

В личке с ботом: `Вы: владелец` или просто скрыть рядную строку. Все capabilities включены, поэтому раздел «Функции» содержит только информационный текст без тоглов; «Чат-админы» скрыт.

### 9.2. Список capability-групп (уровень 1)

Split-row pattern: широкая кнопка тоглит группу, иконка `⚙` справа открывает drill-down.

```
📦 Функции — {chat_name}

[ ✅ AI-помощник       ]  [ ⚙ ]
[ ➖ Транскрибация     ]  [ ⚙ ]
[ ❌ Шутки             ]  [ ⚙ ]
[ ✅ Трекеры           ]  [ ⚙ ]
[ ❌ Модерация         ]  [ ⚙ ]
[ ‹ ]  [ 1/2 ]  [ › ]
[ ⏎ Назад ]
```

Иконки состояний:
- `✅` — capability включена И все фичи внутри включены
- `❌` — capability выключена
- `➖` — capability включена, но часть фич внутри в `disabled_features`

Поведение тогла:
- `✅` → `❌`: убрать capability из `enabled_capabilities`
- `❌` → `✅`: добавить в `enabled_capabilities`, очистить `disabled_features` от этой группы
- `➖` → `✅`: убрать из `disabled_features` все фичи этой группы

Пагинация — через `@paginated("settings:caps", per_page=8, ...)`, метаданные — `str(chat_id)`.

Callback schemas:
- `settings:cap_toggle` schema `<chat_id:int>|<cap:str>`
- `settings:cap_drill` schema `<chat_id:int>|<cap:str>`

### 9.3. Drill-down уровня 2 (фичи внутри группы)

```
📦 AI-помощник — {chat_name}

[ ✅ /ai            ]
[ ✅ /pasha         ]
[ ❌ /diana         ]
[ ✅ /translate     ]
[ ✅ AI-related (пассивно) ]

[ Включить все ] [ Выключить все ]
[ ⏎ Назад ]
```

Подпись фичи: если у неё есть `command` → `/<command>`. Если reactor (нет команды) → `<Имя> (пассивно)` — взять `description` либо имя класса без суффикса.

Тогл фичи внутри drill:
- если capability у чата выключена → автоматически включить её при попытке включить фичу (или вывести подсказку — на выбор реализатора; рекомендую авто-включение для UX).
- иначе: добавить/убрать `feature_slug(cls)` в/из `disabled_features`.

«Включить все» / «Выключить все» — очистить или заполнить `disabled_features` всеми slug этой capability.

Callback `settings:feat_toggle` schema `<chat_id:int>|<cap:str>|<feat:str>`.

### 9.4. Чат-админы

```
👥 Чат-админы — {chat_name}

@alex      ★ chat-admin    [✖]
@vasya                     [+ сделать]
@petya                     [+ сделать]
[ ‹ ]  [ 1/2 ]  [ › ]
[ ⏎ Назад ]
```

Источник списка: `User.chat_ids` содержит `chat_id` → юзер в этом чате.

- `✖` рядом с действующим админом — снять (нельзя снять последнего если не global; запрет сопровождается toast).
- `+ сделать` — назначить.

Видят кнопки: chat_admin или global_admin. Member видит только бейджи без кнопок.

Callback `settings:admin_toggle` schema `<chat_id:int>|<user_id:int>`.

### 9.5. Роли (только global_admin)

```
🎭 Роли

[ Разработчик · 3 чел · 4 прав ]  [ ✏ ]
[ Контент · 1 чел · 2 прав ]      [ ✏ ]
[ + Создать новую роль ]
[ ⏎ Назад ]
```

Тап по широкой кнопке — раскрытие роли:

```
🎭 Разработчик

Permissions:
[ ✅ feature_request.priority ]
[ ✅ feature_request.note     ]
[ ✅ feature_request.status   ]
[ ❌ feature_request.close    ]
[ ‹ ] [ 1/N ] [ › ]

Пользователи:
[ @alex      ✖ ]
[ @bob       ✖ ]
[ + Добавить пользователя ]
[ ⏎ Назад ]
```

`✏` на роли — wizard переименования.
`+ Создать новую роль` — wizard:
1. `ask("name", "Название роли")`
2. `confirm("ok", "Создать?")`
После создания — сразу открыть редактор роли.

`+ Добавить пользователя` — wizard `ask("user", "@username или id")` + резолвер (как в `AdminFeature._resolve`).

Callback schemas:
- `settings:role_open` schema `<role_id:int>`
- `settings:role_perm_toggle` schema `<role_id:int>|<perm:str>`
- `settings:role_user_remove` schema `<role_id:int>|<user_id:int>`

### 9.6. Команда `/settings`

```python
class SettingsFeature(Feature):
    command = "settings"
    description = "Настройки бота для этого чата"

    chat_settings = collection("chat_settings")
    roles = collection("roles")
    user_roles = collection("user_roles")
    users = collection("users")

    @subcommand("", description="Открыть настройки")
    async def open_(self, ctx: FeatureContext):
        await self._render_root(ctx)
```

`SettingsFeature` — всегда-on, в `ALWAYS_ON`, **не имеет** `capability`. Также excluded_from_ai_router=True (не нужна AI-роутингу).

`SettingsFeature.__init__` принимает `_all_handlers` (через тот же механизм, что у `HelpFeature`). Для известных permissions и для capability-инспекции.

---

## 10. Миграция (version 30 → 31)

В `Repository._migrate` (`steward/data/repository.py`) добавить ветку:

```python
if data["version"] == 30:
    chats = data.get("chats", []) or []
    all_caps = ["ai", "transcribe", "rules", "fun", "trackers",
                "chat_meta", "stats", "downloads", "moderation"]
    data["chat_settings"] = [
        {
            "chat_id": c["id"],
            "enabled_capabilities": all_caps,
            "disabled_features": [],
            "chat_admins": [],
            "onboarded": True,
        }
        for c in chats
    ]
    # Преднастроенная роль «Разработчик»
    data["roles"] = [
        {
            "id": 1,
            "name": "Разработчик",
            "permissions": [
                "feature_request.priority",
                "feature_request.note",
                "feature_request.status",
            ],
        }
    ]
    data["user_roles"] = []
    data["version"] = 31
```

Замечания:
- Существующие `diana_allowed_chats` оставляем как есть. Поведение Diana продолжает зависеть от `_is_allowed`, которая смотрит на `db.diana_allowed_chats`. Capability `ai` управляет включена ли Diana как фича вообще. Если `ai` отключена в чате — Diana молчит даже если чат в `diana_allowed_chats`. Это корректно.
- `silenced_chats`, `banned_users`, `joke_settings` — без изменений; работают как раньше, но Enforcer-фичи попадают под capability `moderation`.

---

## 11. Онбординг через `my_chat_member`

### 11.1. Подключить хендлер

`steward/bot/bot.py`, в `Bot.start` после регистрации остальных:
```python
from telegram.ext import ChatMemberHandler
application.add_handler(
    ChatMemberHandler(self._my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER, block=False)
)
```

### 11.2. Логика

```python
async def _my_chat_member(self, update, context):
    cmu = update.my_chat_member
    if cmu is None:
        return
    new = cmu.new_chat_member
    old = cmu.old_chat_member
    bot_joined = (
        new and new.status in ("member", "administrator")
        and (not old or old.status in ("left", "kicked"))
    )
    if not bot_joined:
        return
    chat_id = cmu.chat.id
    adder_id = cmu.from_user.id if cmu.from_user else None

    existing = next((s for s in self.repository.db.chat_settings if s.chat_id == chat_id), None)
    if existing is not None:
        return  # уже был — настройки сохраняются

    settings = ChatSettings(
        chat_id=chat_id,
        enabled_capabilities=set(),
        chat_admins={adder_id} if adder_id else set(),
        onboarded=False,
    )
    self.repository.db.chat_settings.append(settings)
    await self.repository.save()

    greeting = (
        "Привет! Я выключен по умолчанию.\n"
        f"{'@' + adder_username if adder_username else 'Админ'}, "
        "ты теперь chat-admin — открой настройки и включи что нужно."
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚙ Открыть настройки", callback_data="settings:root|" + str(chat_id))
    ]])
    await self.bot.send_message(chat_id, greeting, reply_markup=kb)
```

Callback `settings:root|<chat_id>` — открыть корень настроек (используется и в onboarding-кнопке, и в кнопке «⏎ Назад» из всех drill-down).

### 11.3. Что НЕ делаем

- Не отправляем приветствие в существующих чатах (миграция уже выставила `onboarded=True`).
- Не пытаемся угадать chat_admin для существующих чатов — глобальные админы сами назначат через `/settings`.

---

## 12. Web app

### 12.1. Endpoints

В `steward/api/server.py` (registrar — у нижней части файла, см. `app.router.add_get(...)`):

```
GET    /api/chats/{chat_id}/settings              -> { enabled_capabilities, disabled_features, chat_admins, capabilities_meta }
PATCH  /api/chats/{chat_id}/settings              { enabled_capabilities?, disabled_features? }
POST   /api/chats/{chat_id}/admins                { user_id }
DELETE /api/chats/{chat_id}/admins/{user_id}
GET    /api/chats                                  -> чаты, где caller chat_admin или global_admin

GET    /api/roles                                  -> только global_admin
POST   /api/roles                                  { name, permissions? }
PATCH  /api/roles/{role_id}                        { name?, permissions? }
DELETE /api/roles/{role_id}
POST   /api/roles/{role_id}/users                  { user_id }
DELETE /api/roles/{role_id}/users/{user_id}

GET    /api/permissions                            -> [{ slug, used_by: [feature_name, subcommand] }]
```

Auth: на `/api/chats/*` — caller должен быть chat_admin или global_admin для chat_id. На `/api/roles/*` и `/api/permissions` — только global_admin. `/api/chats/{chat_id}/settings` GET — позволить любому участнику чата (read-only через UI; PATCH — только chat_admin/global).

### 12.2. Фронтенд

Новая страница `web/src/pages/SettingsPage.jsx`. Структура:

- Селектор чата (если у юзера несколько). Хранить в URL: `/settings/:chatId`.
- Три таба:
  - **Функции** — список групп с тоглом + раскрытие на отдельные фичи.
  - **Чат-админы** — список юзеров чата с тоглом chat_admin.
  - **Роли** — только если caller global_admin. CRUD ролей, привязка permissions, привязка юзеров. Чекбоксы permissions берутся из `GET /api/permissions`.

Дизайн-гайд для интерактивности — `web/`-skill «lively-web» (применять при работе в этом каталоге).

Иконка/раздел в боковом меню (`web/src/layouts/...`) — добавить ссылку на `/settings`.

---

## 13. Этапы реализации

Делать PR-ами в этом порядке. Каждый этап self-contained, не ломает прод (всё дефолтно ВКЛ).

### Этап 1 — Storage + миграция

Создать:
- `steward/data/models/role.py`
- `steward/data/models/chat_settings.py`

Изменить:
- `steward/data/models/db.py` — поля `roles`, `user_roles`, `chat_settings`, `version=31`.
- `steward/data/repository.py` — ветка миграции, хелперы (`chat_settings_for`, `is_capability_enabled`, `is_chat_admin`, `permissions_of`, `gated_permissions`, `has_permission`).
- `db.json` миграция авто (на старте).

Тесты:
- `tests/test_migration_v31.py` — проверка что существующие чаты получили все capabilities + создалась роль Разработчик.

### Этап 2 — CAPABILITIES реестр + enforcement (без UI)

Изменить:
- `steward/features/registry.py` — `CAPABILITIES`, `ALWAYS_ON`, `CAPABILITY_LABELS`, хелперы.
- `steward/handlers/handler.py` — property `capability`.
- `steward/bot/bot.py` — `_validate_access`, обработка выключенной capability для команд.
- `steward/framework/subcommand.py` — поле `permission` в `Subcommand`.
- `steward/framework/feature.py` — permission-чек в `_dispatch_subcommand`.

Поведение: всё включено по дефолту → ничего не ломается. Если тестово выставить `enabled_capabilities=set()` для чата — все фичи в нём перестают работать.

Тесты:
- `tests/test_capability_enforcement.py` — фича доступна когда capability включена, недоступна когда выключена; reactor молчит, команда отвечает «выключено».
- `tests/test_permission_gating.py` — permission открыт пока не в роли; после создания роли с этой permission — только владельцы роли могут вызывать.

### Этап 3 — `my_chat_member` хендлер + chat_admin автоназначение

Изменить:
- `steward/bot/bot.py` — регистрация `ChatMemberHandler`, метод `_my_chat_member`.

Без UI пока. Просто бот при добавлении создаёт ChatSettings с adder в `chat_admins`. Приветственное сообщение можно отдельным toggle через env (например `BOT_ONBOARDING_GREETING=1`) — на время разработки UI отключать.

Тест:
- `tests/test_onboarding.py` — фейковый my_chat_member update → создан ChatSettings, chat_admins содержит adder.

### Этап 4 — `SettingsFeature` v1: функции + чат-админы

Создать `steward/features/settings.py`:
- `SettingsFeature(Feature)` с `command="settings"`.
- Подкоманда `""` — корневое сообщение.
- 4 paginated: `caps_l1`, `caps_l2`, `chat_admins`, (роли в Этапе 6).
- callbacks: `settings:root`, `settings:cap_toggle`, `settings:cap_drill`, `settings:feat_toggle`, `settings:cap_all_on`, `settings:cap_all_off`, `settings:admin_toggle`, `settings:tab_chats`, `settings:tab_admins`.

Регистрация:
- В `registry.py`: импорт + добавить в `ALWAYS_ON`. В `COMMANDS` тоже добавить (capability=None → enforcement пропускает; ALWAYS_ON для другой защиты от чужих фильтров).
- В `__init__` подкласса `SettingsFeature` принять `_all_handlers` через паттерн `HelpFeature` и инициализацию в `main.py`.

Тесты:
- `tests/test_settings_ui.py` — корневое сообщение содержит правильные счётчики; тогл capability меняет состояние; member без флага chat_admin не видит управляющих кнопок.

### Этап 5 — Помечаем `FeatureRequestFeature` permissions

Изменить:
- `steward/features/feature_request.py` — добавить `permission=` к подкомандам priority/note/done/deny/reopen/inprogress/testing.

Существующий ручной чек `_can_edit` (если есть) — оставить как добавочную защиту для автор-only.

Тесты:
- `tests/test_feature_request_permissions.py` — без ролей все могут вызывать; с ролью Разработчик и юзером не в ней — отказ; добавили юзера в роль — снова доступ.

### Этап 6 — Роли в `/settings` (global_admin only)

Расширить `SettingsFeature`:
- Таб «🎭 Роли» — paginated.
- Drill в роль — paginated permissions (известные из реестра) + paginated юзеров роли.
- Wizard «создать роль» / «переименовать роль» / «добавить юзера».
- Callback schemas из §9.5.

Тесты:
- `tests/test_roles_management.py` — global_admin создаёт роль, переименовывает, добавляет permission, добавляет юзера; non-global видит только инфо.

### Этап 7 — Web SettingsPage

Изменить:
- `steward/api/server.py` — endpoints из §12.1.
- `web/src/pages/SettingsPage.jsx` — три таба.
- `web/src/api/client.js` — методы.
- `web/src/App.jsx` — маршруты `/settings`, `/settings/:chatId`.
- `web/src/layouts/...` — пункт меню.

Применять `lively-web`-skill для UI.

Тесты:
- API: `tests/test_settings_api.py` — RBAC проверки (не-админ не видит роли, member чата не редактирует caps).
- Web: ручная проверка через `npm run dev` + Telegram WebApp на staging.

### Этап 8 — Обновление документации

Изменить:
- `FEATURES.md` — раздел «Capability и permission новой фичи».
- `Readme.md` — упомянуть `/settings`.
- Этот файл `docs/settings.md` — пометить «implemented» и оставить как референс.

---

## 14. Edge cases и решения

| Кейс | Решение |
|---|---|
| Бот в личке | `effective_chat.type == "private"` → биппассим capability-чек, юзер всегда «владелец», capabilities считаем ВКЛ. |
| Чата нет в `ChatSettings` (старый чат добавил сообщение до миграции) | `chat_settings_for` создаёт запись с `enabled_capabilities=ALL` (как существующие при миграции). |
| Adder бота забыл/ушёл | Любой global_admin может выдать chat_admin через `/settings` или через web. |
| Снять последнего chat_admin | Запрещено если в чате нет global_admin прямо сейчас? Нет — упрощаем: всегда разрешаем, восстановление через global_admin. |
| Пользователь не в `db.users` (не написал ничего) | Список «👥 Чат-админы» строится из `User.chat_ids`. Назначить можно только тех, кто написал хоть раз. Допустимо. |
| Удаление роли с юзерами внутри | При delete роли — каскадно удаляем все `UserRole` с этим `role_id`. |
| Permission удалена из всех ролей | Автоматически становится открытой (через `gated_permissions()`). |
| Subcommand с `admin=True` и `permission="..."` | Сначала проверяем `admin` (global_admin), затем `permission`. Глобальный админ биппасит permission в любом случае. |
| Reactor (`@on_message`) фичи без `command` | capability-чек применяется к классу. Permission на reactor не вешаем (декларация `permission=` есть только у subcommand). |
| Конкурентное редактирование одного callback message | Стандартное поведение пагинатора + edit. Если устарело — `BadRequest "query too old"` ловим как в `_safe_post_action`. |

---

## 15. Что НЕ делаем (явно out of scope)

- Кастомные роли per-chat (роли только глобальные).
- Permission на reactor-handlers.
- Импорт/экспорт настроек между чатами.
- Версионирование ролей / audit-log изменений.
- Группировка permissions в bundle-presets («все FR разрешения», «все billing разрешения») — global_admin собирает руками.
- Миграция `diana_allowed_chats` / `silenced_chats` / `joke_settings` в `ChatSettings` — оставляем рядом.
- Уведомления юзерам об изменении их роли.

---

## 16. Файлы, которые точно тронем (чек-лист)

Новые:
- `steward/data/models/role.py`
- `steward/data/models/chat_settings.py`
- `steward/features/settings.py`
- `web/src/pages/SettingsPage.jsx`
- `tests/test_migration_v31.py`
- `tests/test_capability_enforcement.py`
- `tests/test_permission_gating.py`
- `tests/test_settings_ui.py`
- `tests/test_feature_request_permissions.py`
- `tests/test_roles_management.py`
- `tests/test_settings_api.py`
- `tests/test_onboarding.py`

Изменяемые:
- `steward/data/models/db.py`
- `steward/data/repository.py`
- `steward/features/registry.py`
- `steward/features/feature_request.py`
- `steward/features/_special/help.py`
- `steward/handlers/handler.py`
- `steward/framework/subcommand.py`
- `steward/framework/feature.py`
- `steward/bot/bot.py`
- `main.py` (передать `_all_handlers` в `SettingsFeature` как у `HelpFeature`)
- `steward/api/server.py`
- `web/src/api/client.js`
- `web/src/App.jsx`
- `web/src/layouts/*` (пункт меню)
- `FEATURES.md`

---

## 17. Команда запуска для проверки

После каждого этапа:
- `pytest -x` — все тесты должны проходить.
- `make` (если есть в Makefile) или `python main.py` локально с тестовым токеном — проверить что `/settings` открывается, тоглы работают, выключенные фичи реально не отвечают.
- Web: `cd web && npm run dev` — открыть локально, проверить таб.

Готовность к мержу каждого PR: green CI + ручная проверка golden path.
