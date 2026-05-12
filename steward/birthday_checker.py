import asyncio
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram.ext import ExtBot

from steward.data.models.birthday import Birthday
from steward.data.repository import Repository
from steward.helpers.ai import (
    GROK_SHORT_AGGRESSIVE,
    Model,
    OpenRouterModel,
    make_openrouter_query,
    make_text_query,
)

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Minsk")
CHECK_TIME = time(hour=9, minute=0)


_CELEBRITY_PROMPT = """Сегодня день рождения у публичной личности.

Имя: {name}
Возраст: {age} лет
Кто это (baseline): {description}

Через веб-поиск найди 1-3 свежих факта/мема/новости/прикола про этого человека за последние ~12 месяцев (или самый известный недавний инфоповод). Опирайся на реальные источники.

Напиши поздравление с днём рождения от лица бота в чате друзей:
- 3-5 предложений
- с юмором, с приколами, с лёгкой подколкой
- обязательно вплети свежий факт/новость, чтобы каждый год поздравление было разное
- по-русски, без markdown, без хэштегов
- без обращения "дорогой" и пафоса

Верни ТОЛЬКО текст поздравления, ничего больше."""


class BirthdayChecker:
    def __init__(self, repository: Repository, bot: ExtBot[None]):
        self._repository = repository
        self._bot = bot

    def _next_check(self) -> datetime:
        now = datetime.now(TIMEZONE)
        target = datetime.combine(now.date(), CHECK_TIME, tzinfo=TIMEZONE)
        if now >= target:
            target += timedelta(days=1)
        return target

    async def start(self):
        while True:
            target = self._next_check()
            delay = (target - datetime.now(TIMEZONE)).total_seconds()
            logger.info(f"Birthday check scheduled at {target.isoformat()}, sleeping {delay:.0f}s")
            await asyncio.sleep(delay)

            try:
                await self._check_birthdays()
            except Exception:
                logger.exception("Birthday check failed")

    async def _check_birthdays(self):
        now = datetime.now(TIMEZONE)
        day, month = now.day, now.month

        for b in self._repository.db.birthdays:
            if b.day == day and b.month == month:
                try:
                    text = await self._make_greeting(b, now.year)
                    await self._bot.send_message(b.chat_id, text)
                except Exception:
                    logger.exception(f"Failed to congratulate {b.name} in chat {b.chat_id}")

    async def _make_greeting(self, b: Birthday, current_year: int) -> str:
        if b.description:
            age = max(0, current_year - b.year) if b.year else None
            age_str = str(age) if age is not None else "?"
            prompt = _CELEBRITY_PROMPT.format(
                name=b.name, age=age_str, description=b.description,
            )
            try:
                return await make_openrouter_query(
                    0,
                    OpenRouterModel.GROK_4_FAST_ONLINE,
                    [("user", prompt)],
                    timeout_seconds=90.0,
                )
            except Exception:
                logger.exception("celebrity greeting via online model failed, falling back")
        return await make_text_query(
            0,
            Model.SMART,
            [("user", f"Поздравь с днём рождения {b.name}")],
            GROK_SHORT_AGGRESSIVE,
        )
