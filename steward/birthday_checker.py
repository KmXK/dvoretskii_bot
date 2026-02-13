import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram.ext import ExtBot

from steward.data.repository import Repository
from steward.helpers.ai import GROK_SHORT_AGGRESSIVE, OpenRouterModel, make_openrouter_query

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Minsk")
CHECK_TIME = time(hour=9, minute=0)


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
                    text = await make_openrouter_query(
                        0,
                        OpenRouterModel.GROK_4_FAST,
                        [("user", f"Поздравь с днём рождения {b.name}")],
                        GROK_SHORT_AGGRESSIVE,
                    )
                    await self._bot.send_message(b.chat_id, text)
                except Exception:
                    logger.exception(f"Failed to congratulate {b.name} in chat {b.chat_id}")
