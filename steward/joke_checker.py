import asyncio
import logging
from datetime import datetime, timezone

from telegram.ext import ExtBot
from telethon import TelegramClient

from steward.data.repository import Repository

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 5 * 60  # check every 5 minutes

JOKE_CHANNEL = "baneksru"
_MAX_SENT_IDS = 200  # cap per chat to avoid unbounded growth


async def get_joke_from_channel(
    client: TelegramClient,
    sent_ids: set[int],
) -> tuple[int, str] | None:
    """Returns (message_id, text) of the latest unsent joke, or None if all recent posts exhausted."""
    try:
        messages = await client.get_messages(JOKE_CHANNEL, limit=50)
        for msg in messages:  # newest first
            if msg.text and msg.id not in sent_ids:
                return msg.id, msg.text
    except Exception:
        logger.exception("Failed to fetch jokes from channel %s", JOKE_CHANNEL)
    return None


def _track_sent(existing: list[int], post_id: int) -> list[int]:
    updated = [i for i in existing if i != post_id] + [post_id]
    return updated[-_MAX_SENT_IDS:]


class JokeChecker:
    def __init__(self, repository: Repository, bot: ExtBot[None], client: TelegramClient):
        self._repository = repository
        self._bot = bot
        self._client = client

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

            sent_ids = set(db.joke_sent_post_ids.get(chat_id, []))
            result = await get_joke_from_channel(self._client, sent_ids)
            if result is None:
                logger.warning("No new jokes available for chat %s", chat_id)
                continue

            post_id, text = result
            try:
                await self._bot.send_message(chat_id, text)
                db.last_joke_sent_at[chat_id] = now
                db.joke_sent_post_ids[chat_id] = _track_sent(
                    db.joke_sent_post_ids.get(chat_id, []), post_id
                )
                await self._repository.save()
                logger.info("Sent joke (post %s) to chat %s after %.0fs of silence",
                            post_id, chat_id, (now - last_msg).total_seconds())
            except Exception:
                logger.exception("Failed to send joke to chat %s", chat_id)
