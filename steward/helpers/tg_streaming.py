"""Stream an async iterable of text chunks into a single Telegram message.

Usage:
    bot_message = await stream_reply(
        target=user_message,          # telegram.Message to reply to
        chunks=openrouter_stream(...) # async iterator yielding str pieces
    )

The helper sends a placeholder reply, then edits it as chunks arrive, with
throttling so we never exceed Telegram's edit rate limits (~1 edit/sec per
message). At the end it sends one final edit with the complete text and the
preferred parse_mode (markdown when it's valid, otherwise plain text).
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from typing import AsyncIterator

from telegram import Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

from steward.helpers.thinking import random_phrase
from steward.helpers.tg_update_helpers import is_valid_markdown

logger = logging.getLogger(__name__)

_DEFAULT_MIN_INTERVAL = 1.2  # seconds between edits
_ANIMATION_INTERVAL = 1.3  # seconds between dot-animation frames
_TG_TEXT_LIMIT = 4096


def _strip_trailing_dots(text: str) -> str:
    return text.rstrip("…").rstrip(".").rstrip()


async def _animate_placeholder(
    bot_message: Message,
    base: str,
    stop: asyncio.Event,
) -> None:
    """Cycle the trailing dots on `bot_message` (1 → 2 → 3) until `stop` is set."""
    n = 1
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_ANIMATION_INTERVAL)
            return
        except asyncio.TimeoutError:
            pass
        n = n % 3 + 1
        text = f"<i>{html.escape(base + '.' * n)}</i>"
        try:
            await bot_message.edit_text(text, parse_mode=ParseMode.HTML)
        except RetryAfter as e:
            try:
                await asyncio.wait_for(stop.wait(), timeout=float(e.retry_after))
                return
            except asyncio.TimeoutError:
                continue
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                logger.debug("placeholder animation BadRequest: %s", e)


async def stream_reply(
    target: Message,
    chunks: AsyncIterator[str],
    *,
    placeholder: str | None = None,
    min_edit_interval: float = _DEFAULT_MIN_INTERVAL,
) -> Message:
    """Send a reply to `target` and progressively fill it with streamed text.

    Returns the sent Message (with its final text applied).
    """
    if placeholder is None:
        placeholder = random_phrase()
    base = _strip_trailing_dots(placeholder) or placeholder
    bot_message = await target.reply_text(
        f"<i>{html.escape(base + '.')}</i>",
        parse_mode=ParseMode.HTML,
    )

    stop_animation = asyncio.Event()
    animation_task = asyncio.create_task(
        _animate_placeholder(bot_message, base, stop_animation)
    )

    buffer: list[str] = []
    last_edit_at = 0.0
    last_text = ""
    got_anything = False

    async def _stop_animation():
        if not stop_animation.is_set():
            stop_animation.set()
            try:
                await animation_task
            except Exception as e:
                logger.debug("animation task ended with: %s", e)

    async for chunk in chunks:
        if not chunk:
            continue
        if not got_anything:
            await _stop_animation()
        buffer.append(chunk)
        got_anything = True
        text = "".join(buffer)
        if len(text) > _TG_TEXT_LIMIT:
            text = text[:_TG_TEXT_LIMIT]
        now = time.monotonic()
        if now - last_edit_at < min_edit_interval:
            continue
        if text == last_text:
            continue
        try:
            await bot_message.edit_text(text)
            last_edit_at = now
            last_text = text
        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after))
        except BadRequest as e:
            # "Message is not modified" is safe to ignore; other errors we log
            # but keep accumulating so the final edit still applies.
            if "not modified" not in str(e).lower():
                logger.warning("stream edit BadRequest: %s", e)

    await _stop_animation()

    final_text = "".join(buffer) if got_anything else ""
    if not final_text:
        try:
            await bot_message.edit_text("(пусто)")
        except BadRequest:
            pass
        return bot_message

    if len(final_text) > _TG_TEXT_LIMIT:
        final_text = final_text[:_TG_TEXT_LIMIT]

    parse_mode: ParseMode | None = (
        ParseMode.MARKDOWN if is_valid_markdown(final_text) else None
    )
    if final_text == last_text and parse_mode is None:
        return bot_message
    try:
        await bot_message.edit_text(final_text, parse_mode=parse_mode)
    except RetryAfter as e:
        await asyncio.sleep(float(e.retry_after))
        await bot_message.edit_text(final_text, parse_mode=parse_mode)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return bot_message
        # Markdown parse failure — retry without parse_mode.
        if parse_mode is not None:
            try:
                await bot_message.edit_text(final_text)
            except BadRequest as e2:
                logger.warning("stream final edit failed: %s", e2)
        else:
            logger.warning("stream final edit failed: %s", e)
    return bot_message
