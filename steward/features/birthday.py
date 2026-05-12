import json
import logging
import random
import re
import time
import uuid
from datetime import datetime

from steward.data.models.birthday import Birthday
from steward.framework import (
    INITIATOR_ONLY,
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    on_callback,
    subcommand,
)
from steward.helpers.ai import OpenRouterModel, make_openrouter_query
from steward.helpers.tg_streaming import edit_with_animated_status

logger = logging.getLogger(__name__)


MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

DATE_PATTERN = re.compile(
    r"^(?P<name>.+?)\s+(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?:\.(?P<year>\d{4}))?$"
)

_LOOKUP_PHRASES = (
    "Рою архивы знаменитостей",
    "Сверяюсь с Википедией",
    "Листаю IMDb",
    "Опрашиваю фанатские форумы",
    "Звоню агенту знаменитости",
    "Тыкаю палкой в инет",
    "Спрашиваю у тёти Гугл",
    "Прошу у нейросети досье",
    "Заглядываю в звёздный календарь",
    "Сверяюсь с астрологом",
)


_LOOKUP_PROMPT = """Ты помогаешь найти дату рождения публичной личности через веб-поиск.

Имя для поиска: {name}

Правила:
1. Используй веб-поиск. Сверь минимум 2 разных источника (Википедия на разных языках, IMDb, новостные статьи, официальные сайты или соцсети, базы вроде Famous Birthdays).
2. Если источники расходятся в дате — верни {{"error": "источники расходятся"}}.
3. Если ничего не нашёл или человек не публичный — верни {{"error": "не нашёл"}}.
4. description — 1-2 предложения по-русски о том, чем известен человек, с лёгкой иронией или забавным фактом.
5. sources — реальные URL из веб-поиска (минимум 2), на которые ты опирался.

Верни ТОЛЬКО валидный JSON без markdown-обёрток, без текста до или после:
{{
  "day": <число 1-31>,
  "month": <число 1-12>,
  "year": <год>,
  "description": "<строка>",
  "sources": ["<url1>", "<url2>"]
}}

Или при ошибке:
{{"error": "<краткая причина>"}}
"""


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _format_date(day: int, month: int, year: int | None) -> str:
    base = f"{day} {MONTHS[month - 1]}"
    return f"{base} {year}" if year else base


class BirthdayFeature(Feature):
    command = "birthday"
    description = "Дни рождения (свои и знаменитостей)"
    help_examples = [
        "/birthday — список именинников",
        "/birthday Иван 15.03 — добавить дату",
        "/birthday Иван 15.03.1990 — добавить с годом",
        "/birthday Иван Золо — найти ДР знаменитости автоматически",
        "/birthday remove Иван — удалить",
    ]

    birthdays = collection("birthdays")

    def __init__(self):
        super().__init__()
        self._pending: dict[str, dict] = {}

    @subcommand("", description="Список именинников")
    async def view(self, ctx: FeatureContext):
        chat_id = ctx.chat_id
        items = sorted(
            (b for b in self.birthdays if b.chat_id == chat_id),
            key=lambda b: (b.month, b.day),
        )
        if not items:
            await ctx.reply("Список именинников пуст")
            return
        lines = ["Дни рождения:", ""]
        for b in items:
            lines.append(f"{b.name} — {_format_date(b.day, b.month, b.year)}")
        await ctx.reply("\n".join(lines))

    @subcommand("remove <name:rest>", description="Удалить", admin=True)
    async def remove(self, ctx: FeatureContext, name: str):
        item = self.birthdays.find_by(name=name, chat_id=ctx.chat_id)
        if item is None:
            await ctx.reply("Такого именинника нет в списке")
            return
        self.birthdays.remove(item)
        await self.birthdays.save()
        await ctx.reply("Удалил именинника")

    @subcommand(
        "<args:rest>",
        description="Добавить (<имя> ДД.ММ[.ГГГГ]) или найти ДР знаменитости (<имя>)",
        catchall=True,
    )
    async def add(self, ctx: FeatureContext, args: str):
        args = args.strip()
        if not args:
            return False
        m = DATE_PATTERN.fullmatch(args)
        if m:
            await self._add_manual(ctx, m)
        else:
            await self._lookup_celebrity(ctx, args)

    async def _add_manual(self, ctx: FeatureContext, m: re.Match):
        name = m.group("name").strip()
        day, month = int(m.group("day")), int(m.group("month"))
        year_raw = m.group("year")
        year = int(year_raw) if year_raw else None
        if not (1 <= day <= 31 and 1 <= month <= 12):
            await ctx.reply("Некорректная дата")
            return
        existing = self.birthdays.find_by(name=name, chat_id=ctx.chat_id)
        if existing:
            existing.day = day
            existing.month = month
            existing.year = year
            existing.description = ""
        else:
            self.birthdays.add(
                Birthday(
                    name=name, day=day, month=month, chat_id=ctx.chat_id,
                    year=year, description="",
                )
            )
        await self.birthdays.save()
        await ctx.reply(f"Запомнил: {name} — {_format_date(day, month, year)}")

    async def _lookup_celebrity(self, ctx: FeatureContext, name: str):
        if ctx.message is None:
            await ctx.reply("Не из чата — не получится показать поиск.")
            return

        async def _work():
            raw = await make_openrouter_query(
                ctx.user_id,
                OpenRouterModel.GROK_4_FAST_ONLINE,
                [("user", _LOOKUP_PROMPT.format(name=name))],
                timeout_seconds=90.0,
            )
            return self._parse_lookup_response(raw)

        def _render(result):
            if isinstance(result, Exception):
                logger.exception("birthday lookup failed for %s: %s", name, result)
                return (f"Не получилось спросить AI: {str(result)[:200]}", None, False)
            if "error" in result:
                return (f"Не нашёл ДР для «{name}»: {result['error']}", None, False)

            token = uuid.uuid4().hex[:12]
            self._pending[token] = {
                "name": name,
                "day": result["day"],
                "month": result["month"],
                "year": result["year"],
                "description": result["description"],
                "sources": result["sources"],
                "chat_id": ctx.chat_id,
                "created_at": time.time(),
            }
            self._evict_old_pending()

            age = self._age(result["year"])
            age_str = f" ({age} лет)" if age is not None else ""
            src_lines = "\n".join(f"• {url}" for url in result["sources"][:5]) or "—"
            text = (
                f"🎂 <b>{name}</b>\n"
                f"📅 {_format_date(result['day'], result['month'], result['year'])}{age_str}\n\n"
                f"{result['description']}\n\n"
                f"📎 <b>Источники</b>:\n{src_lines}\n\n"
                f"Сохранить в список?"
            )
            kb = Keyboard.row(
                self.cb("birthday:confirm").button(
                    "✅ Сохранить", token=token, answer="yes", initiator=ctx.user_id,
                ),
                self.cb("birthday:confirm").button(
                    "❌ Отмена", token=token, answer="no", initiator=ctx.user_id,
                ),
            )
            return (text, kb, True)

        await edit_with_animated_status(
            ctx.message,
            _work(),
            _render,
            placeholder=random.choice(_LOOKUP_PHRASES),
        )

    @on_callback(
        "birthday:confirm",
        schema="<token:str>|<answer:literal[yes|no]>|<initiator:int>",
        access=INITIATOR_ONLY,
    )
    async def on_confirm(
        self, ctx: FeatureContext, token: str, answer: str, initiator: int,
    ):
        data = self._pending.pop(token, None)
        if data is None:
            await ctx.edit("Это подтверждение протухло. Запусти /birthday <имя> заново.")
            return
        if answer == "no":
            await ctx.edit("Отменено")
            return
        existing = self.birthdays.find_by(name=data["name"], chat_id=data["chat_id"])
        if existing:
            existing.day = data["day"]
            existing.month = data["month"]
            existing.year = data["year"]
            existing.description = data["description"]
        else:
            self.birthdays.add(
                Birthday(
                    name=data["name"],
                    day=data["day"],
                    month=data["month"],
                    chat_id=data["chat_id"],
                    year=data["year"],
                    description=data["description"],
                )
            )
        await self.birthdays.save()
        await ctx.edit(
            f"Запомнил: {data['name']} — "
            f"{_format_date(data['day'], data['month'], data['year'])}"
        )

    @staticmethod
    def _parse_lookup_response(raw: str) -> dict:
        cleaned = _strip_json_fence(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("birthday lookup returned non-json: %s", raw[:500])
            return {"error": "не понял ответ AI"}
        if not isinstance(data, dict):
            return {"error": "не понял ответ AI"}
        if "error" in data:
            return {"error": str(data["error"])[:200]}
        try:
            day = int(data["day"])
            month = int(data["month"])
            year = int(data["year"])
        except (KeyError, TypeError, ValueError):
            return {"error": "не хватает полей в ответе"}
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1800 <= year <= 2100):
            return {"error": "невалидная дата"}
        sources_raw = data.get("sources") or []
        sources = (
            [str(s) for s in sources_raw if isinstance(s, (str, int))]
            if isinstance(sources_raw, list) else []
        )
        return {
            "day": day,
            "month": month,
            "year": year,
            "description": str(data.get("description", "")),
            "sources": sources,
        }

    def _evict_old_pending(self):
        if len(self._pending) <= 50:
            return
        cutoff = time.time() - 600
        self._pending = {
            tok: d for tok, d in self._pending.items()
            if d.get("created_at", 0) > cutoff
        }
        if len(self._pending) > 50:
            ordered = sorted(self._pending.items(), key=lambda x: x[1].get("created_at", 0))
            self._pending = dict(ordered[-50:])

    @staticmethod
    def _age(year: int | None) -> int | None:
        if not year:
            return None
        return max(0, datetime.now().year - year)
