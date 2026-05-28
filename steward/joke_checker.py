import asyncio
import logging
from datetime import datetime, timezone

from telegram.ext import ExtBot

from steward.data.repository import Repository
from steward.helpers.ai import OpenRouterModel, make_openrouter_query

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 5 * 60  # check every 5 minutes

_JOKE_MODEL = OpenRouterModel.GROK_4_FAST

JOKE_SYSTEM_PROMPT = (
    "Ты генератор смешных анекдотов для русскоязычного телеграм-чата. "
    "Придумай один короткий смешной анекдот или шутку в стиле зумеров (Gen Z). "
    "Стиль: абсурдный юмор, ирония, ситуационный стёб, жиза 2020-х. "
    "Можно: чёрный юмор, самоирония, про интернет/соцсети/технологии/работу/учёбу. "
    "Не надо: советские анекдоты, классический формат «вопрос — ответ про Вовочку», "
    "пошлятина, расизм, политика. "
    "Формат: только сам анекдот, без вступлений и объяснений. Коротко."
)


async def generate_joke() -> str | None:
    try:
        text = await make_openrouter_query(
            "_joke_checker",
            _JOKE_MODEL,
            [("user", "Придумай анекдот")],
            system_prompt=JOKE_SYSTEM_PROMPT,
            max_tokens=300,
            timeout_seconds=20,
        )
        return text.strip() or None
    except Exception:
        logger.exception("Failed to generate joke via LLM")
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

            # Only send one joke per silence period — skip if already sent since last human message
            last_joke = db.last_joke_sent_at.get(chat_id)
            if last_joke is not None:
                if last_joke.tzinfo is None:
                    last_joke = last_joke.replace(tzinfo=timezone.utc)
                if last_joke >= last_msg:
                    continue

            joke = await generate_joke()
            if not joke:
                logger.warning("Got empty joke, skipping chat %s", chat_id)
                continue

            try:
                await self._bot.send_message(chat_id, joke)
                db.last_joke_sent_at[chat_id] = now
                await self._repository.save()
                logger.info("Sent joke to chat %s after %.0fs of silence", chat_id, (now - last_msg).total_seconds())
            except Exception:
                logger.exception("Failed to send joke to chat %s", chat_id)
