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
2. Если ничего не нашёл или человек не публичный — верни {{"error": "не нашёл"}}.
3. candidates — список вариантов даты. Если все источники сходятся — верни ОДИН вариант. Если расходятся — 2-3 варианта (максимум 3), отсортированных от самого надёжного к наименее. Для каждого варианта sources должен содержать только URL, которые поддерживают именно эту дату (минимум 1 URL на вариант).
4. description — 1-2 предложения по-русски о том, чем известен человек, с лёгкой иронией или забавным фактом.

Верни ТОЛЬКО валидный JSON без markdown-обёрток, без текста до или после:
{{
  "candidates": [
    {{"day": <1-31>, "month": <1-12>, "year": <год>, "sources": ["<url>", ...]}}
  ],
  "description": "<строка>"
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
                code = result["error"]
                logger.info("birthday lookup gave up for %r: %s", name, result)
                if code == "not_found":
                    msg = f"Не нашёл ДР для «{name}». Попробуй уточнить имя."
                else:
                    msg = (
                        f"Не получилось разобрать ответ AI для «{name}». "
                        f"Подробности в логах ({code})."
                    )
                return (msg, None, False)

            candidates = result["candidates"]
            description = result["description"]
            token = uuid.uuid4().hex[:12]
            self._pending[token] = {
                "name": name,
                "description": description,
                "candidates": candidates,
                "chat_id": ctx.chat_id,
                "created_at": time.time(),
            }
            self._evict_old_pending()

            if len(candidates) == 1:
                text = (
                    f"{self._format_single_cut(name, description, candidates[0])}\n\n"
                    f"Сохранить в список?"
                )
                kb = Keyboard.row(
                    self.cb("birthday:pick").button(
                        "✅ Сохранить", token=token, idx=0, initiator=ctx.user_id,
                    ),
                    self.cb("birthday:pick").button(
                        "❌ Отмена", token=token, idx=-1, initiator=ctx.user_id,
                    ),
                )
            else:
                text = self._format_conflict_view(name, description, candidates)
                pick_buttons = [
                    self.cb("birthday:pick").button(
                        f"📅 {_format_date(c['day'], c['month'], c['year'])}",
                        token=token, idx=i, initiator=ctx.user_id,
                    )
                    for i, c in enumerate(candidates)
                ]
                kb = Keyboard.column(*pick_buttons).append_row(
                    self.cb("birthday:pick").button(
                        "❌ Отмена", token=token, idx=-1, initiator=ctx.user_id,
                    )
                )
            return (text, kb, True)

        await edit_with_animated_status(
            ctx.message,
            _work(),
            _render,
            placeholder=random.choice(_LOOKUP_PHRASES),
        )

    @on_callback(
        "birthday:pick",
        schema="<token:str>|<idx:int>|<initiator:int>",
        access=INITIATOR_ONLY,
    )
    async def on_pick(
        self, ctx: FeatureContext, token: str, idx: int, initiator: int,
    ):
        data = self._pending.pop(token, None)
        if data is None:
            await ctx.edit("Это подтверждение протухло. Запусти /birthday <имя> заново.")
            return
        name = data["name"]
        description = data["description"]
        candidates: list[dict] = data["candidates"]
        if idx == -1:
            if len(candidates) == 1:
                cut = self._format_single_cut(name, description, candidates[0])
            else:
                cut = self._format_conflict_cut(name, description, candidates)
            await ctx.edit(f"❌ Отменено\n\n{cut}", html=True)
            return
        if idx < 0 or idx >= len(candidates):
            await ctx.edit("Неизвестный вариант")
            return
        chosen = candidates[idx]
        existing = self.birthdays.find_by(name=name, chat_id=data["chat_id"])
        if existing:
            existing.day = chosen["day"]
            existing.month = chosen["month"]
            existing.year = chosen["year"]
            existing.description = description
        else:
            self.birthdays.add(
                Birthday(
                    name=name,
                    day=chosen["day"],
                    month=chosen["month"],
                    chat_id=data["chat_id"],
                    year=chosen["year"],
                    description=description,
                )
            )
        await self.birthdays.save()
        summary = (
            f"✅ Запомнил: {name} — "
            f"{_format_date(chosen['day'], chosen['month'], chosen['year'])}"
        )
        cut = self._format_single_cut(name, description, chosen)
        await ctx.edit(f"{summary}\n\n{cut}", html=True)

    @classmethod
    def _format_single_cut(cls, name: str, description: str, candidate: dict) -> str:
        age = cls._age(candidate["year"])
        age_str = f" ({age} лет)" if age is not None else ""
        sources = candidate.get("sources") or []
        src_lines = "\n".join(f"• {url}" for url in sources[:5]) or "—"
        return (
            f"<blockquote expandable>"
            f"🎂 <b>{name}</b>\n"
            f"📅 {_format_date(candidate['day'], candidate['month'], candidate['year'])}{age_str}\n\n"
            f"{description}\n\n"
            f"📎 <b>Источники</b>:\n{src_lines}"
            f"</blockquote>"
        )

    @classmethod
    def _format_conflict_body(
        cls, name: str, description: str, candidates: list[dict],
    ) -> str:
        lines = [
            f"🎂 <b>{name}</b>",
            "",
            description,
            "",
            "⚠️ Источники расходятся в дате:",
        ]
        for i, c in enumerate(candidates, 1):
            age = cls._age(c["year"])
            age_str = f" ({age} лет)" if age is not None else ""
            srcs = c.get("sources") or []
            lines.append("")
            lines.append(
                f"<b>{i}. {_format_date(c['day'], c['month'], c['year'])}{age_str}</b>"
            )
            for url in srcs[:3]:
                lines.append(f"  • {url}")
        return "\n".join(lines)

    @classmethod
    def _format_conflict_view(
        cls, name: str, description: str, candidates: list[dict],
    ) -> str:
        body = cls._format_conflict_body(name, description, candidates)
        return f"{body}\n\nВыбери правильную дату:"

    @classmethod
    def _format_conflict_cut(
        cls, name: str, description: str, candidates: list[dict],
    ) -> str:
        body = cls._format_conflict_body(name, description, candidates)
        return f"<blockquote expandable>{body}</blockquote>"

    @staticmethod
    def _parse_lookup_response(raw: str) -> dict:
        cleaned = _strip_json_fence(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("birthday lookup: non-json response: %r", raw[:1000])
            return {"error": "bad_json"}
        if not isinstance(data, dict):
            logger.warning("birthday lookup: non-dict response: %r", raw[:1000])
            return {"error": "bad_shape"}
        if "error" in data:
            return {"error": "not_found", "ai_reason": str(data["error"])[:200]}
        raw_candidates = data.get("candidates")
        if raw_candidates is None and "day" in data:
            raw_candidates = [data]
        if not isinstance(raw_candidates, list) or not raw_candidates:
            logger.warning("birthday lookup: missing candidates: %r", raw[:1000])
            return {"error": "missing_candidates"}
        candidates: list[dict] = []
        seen: set[tuple[int, int, int]] = set()
        rejected: list[dict] = []
        for entry in raw_candidates[:3]:
            if not isinstance(entry, dict):
                rejected.append({"reason": "not_dict", "entry": str(entry)[:200]})
                continue
            try:
                day = int(entry["day"])
                month = int(entry["month"])
                year = int(entry["year"])
            except (KeyError, TypeError, ValueError) as e:
                rejected.append({"reason": f"parse:{e}", "entry": str(entry)[:200]})
                continue
            if not (1 <= day <= 31 and 1 <= month <= 12 and 1800 <= year <= 2100):
                rejected.append({"reason": "out_of_range", "day": day, "month": month, "year": year})
                continue
            key = (day, month, year)
            if key in seen:
                continue
            seen.add(key)
            srcs_raw = entry.get("sources") or []
            srcs = (
                [str(s) for s in srcs_raw if isinstance(s, (str, int))]
                if isinstance(srcs_raw, list) else []
            )
            candidates.append({"day": day, "month": month, "year": year, "sources": srcs})
        if not candidates:
            logger.warning(
                "birthday lookup: all %d candidates rejected (%s); raw=%r",
                len(raw_candidates), rejected, raw[:1000],
            )
            return {"error": "invalid_date"}
        return {
            "candidates": candidates,
            "description": str(data.get("description", "")),
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
