import asyncio
import logging
import os
from datetime import datetime, timezone

from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup
from telegram.ext import ExtBot
from telethon import TelegramClient

from steward.data.repository import Repository

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 5 * 60

JOKE_CHANNELS = ["baneksru", "gold_anekdot"]
_MAX_SENT_IDS = 200

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def get_channel_posts(channel: str) -> list[dict]:
    """Returns [{id, text}] newest-first from a public Telegram channel via HTML."""
    url = f"https://t.me/s/{channel}"
    posts = []
    try:
        proxy_url = os.environ.get("DOWNLOAD_PROXY")
        connector = ProxyConnector.from_url(proxy_url) if proxy_url else None
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        timeout = ClientTimeout(total=30, connect=10)
        async with ClientSession(connector=connector, timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning("Channel %s returned HTTP %s", channel, response.status)
                    return posts
                content = await response.text()

        soup = BeautifulSoup(content, "html.parser")
        for msg_div in soup.find_all("div", class_="tgme_widget_message"):
            data_post = msg_div.get("data-post", "")
            if not data_post:
                continue
            try:
                post_id = int(data_post.split("/")[-1])
            except (ValueError, IndexError):
                continue
            text_el = msg_div.find("div", class_="tgme_widget_message_text")
            if not text_el:
                continue
            text = text_el.get_text(separator="\n").strip()
            if text:
                posts.append({"id": post_id, "text": text})

        posts.sort(key=lambda x: x["id"], reverse=True)
    except Exception:
        logger.exception("Failed to fetch posts from channel %s", channel)
    return posts


async def get_joke(
    sent_keys: set[str],
    last_channel: str | None,
) -> tuple[str, int, str] | None:
    """Returns (channel, post_id, text) picking the latest unsent post, alternating channels."""
    # Rotate so the channel after last_channel is tried first
    if last_channel in JOKE_CHANNELS:
        start = (JOKE_CHANNELS.index(last_channel) + 1) % len(JOKE_CHANNELS)
        order = JOKE_CHANNELS[start:] + JOKE_CHANNELS[:start]
    else:
        order = JOKE_CHANNELS

    for channel in order:
        posts = await get_channel_posts(channel)
        for post in posts:  # newest first
            key = f"{channel}:{post['id']}"
            if key not in sent_keys:
                return channel, post["id"], post["text"]

    return None


def _track_sent(existing: list[str], key: str) -> list[str]:
    updated = [k for k in existing if k != key] + [key]
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

            last_joke = db.last_joke_sent_at.get(chat_id)
            if last_joke is not None:
                if last_joke.tzinfo is None:
                    last_joke = last_joke.replace(tzinfo=timezone.utc)
                if last_joke >= last_msg:
                    continue

            sent_keys = set(db.joke_sent_post_ids.get(chat_id, []))
            last_channel = db.joke_last_channel.get(chat_id)
            result = await get_joke(sent_keys, last_channel)
            if result is None:
                logger.warning("No new jokes available for chat %s", chat_id)
                continue

            channel, post_id, text = result
            try:
                await self._bot.send_message(chat_id, text)
                key = f"{channel}:{post_id}"
                db.last_joke_sent_at[chat_id] = now
                db.joke_sent_post_ids[chat_id] = _track_sent(
                    db.joke_sent_post_ids.get(chat_id, []), key
                )
                db.joke_last_channel[chat_id] = channel
                await self._repository.save()
                logger.info(
                    "Sent joke %s to chat %s after %.0fs of silence",
                    key, chat_id, (now - last_msg).total_seconds(),
                )
            except Exception:
                logger.exception("Failed to send joke to chat %s", chat_id)
