import asyncio
import json
import logging
import random
from datetime import datetime, timezone

import aiohttp
from telegram.ext import ExtBot

from steward.data.repository import Repository

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 5 * 60  # check every 5 minutes

_JOKE_SOURCES = [
    ("rzhunemogu", "http://www.rzhunemogu.ru/RandJSON.aspx?CType=1"),
    ("rzhunemogu_stories", "http://www.rzhunemogu.ru/RandJSON.aspx?CType=2"),
]


async def _fetch_joke() -> str | None:
    name, url = random.choice(_JOKE_SOURCES)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                raw = await resp.text(encoding="windows-1251")
                # Site has unescaped newlines inside JSON strings — fix before parsing
                raw = raw.replace("\r\n", r"\n").replace("\r", r"\n").replace("\n", r"\n")
                data = json.loads(raw)
                text = (data.get("content") or "").replace(r"\n", "\n").strip()
                return text or None
    except Exception:
        logger.exception("Failed to fetch joke from %s (%s)", name, url)
        return None


class JokeChecker:
    def __init__(self, repository: Repository, bot: ExtBot[None]):
        self._repository = repository
        self._bot = bot

    async def start(self):
        while True:
            await asyncio.sleep(CHECK_INTERVAL)
            try:
                await self._check()
            except Exception:
                logger.exception("Joke checker iteration failed")

    async def _check(self):
        now = datetime.now(timezone.utc)
        db = self._repository.db

        for chat_id, threshold in list(db.joke_settings.items()):
            last_msg = db.last_message_at.get(chat_id)
            if last_msg is None:
                continue

            if last_msg.tzinfo is None:
                last_msg = last_msg.replace(tzinfo=timezone.utc)

            if (now - last_msg) < threshold:
                continue

            joke = await _fetch_joke()
            if not joke:
                logger.warning("Got empty joke, skipping chat %s", chat_id)
                continue

            try:
                await self._bot.send_message(chat_id, joke)
                db.last_message_at[chat_id] = now
                await self._repository.save()
                logger.info("Sent joke to chat %s after %.0fs of silence", chat_id, (now - last_msg).total_seconds())
            except Exception:
                logger.exception("Failed to send joke to chat %s", chat_id)
