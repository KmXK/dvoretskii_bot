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
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

from telegram import Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

from steward.helpers.md_to_html import md_to_html
from steward.helpers.thinking import random_phrase

T = TypeVar("T")

logger = logging.getLogger(__name__)

_DEFAULT_MIN_INTERVAL = 1.2  # seconds between edits
_ANIMATION_INTERVAL = 1.3  # seconds between dot-animation frames
_TG_TEXT_LIMIT = 4096


def _strip_trailing_dots(text: str) -> str:
    return text.rstrip("…").rstrip(".").rstrip()


async def _animate_placeholder(
    bot_message: Message,
    base_ref: list[str],
    stop: asyncio.Event,
) -> None:
    """Cycle the trailing dots on `bot_message` (1 → 2 → 3) until `stop` is set.

    `base_ref` is a single-element list so the caller can hot-swap the base
    phrase (e.g. when a contextual placeholder arrives late).
    """
    n = 1
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_ANIMATION_INTERVAL)
            return
        except asyncio.TimeoutError:
            pass
        n = n % 3 + 1
        text = f"<i>{html.escape(base_ref[0] + '.' * n)}</i>"
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


async def _upgrade_placeholder(
    bot_message: Message,
    base_ref: list[str],
    upgrade: Awaitable[str | None],
    stop: asyncio.Event,
) -> None:
    """Wait for a better placeholder; when it arrives, swap `base_ref[0]` and
    render it immediately (with one dot, to keep the animation in sync)."""
    try:
        new_phrase = await upgrade
    except Exception as e:
        logger.debug("placeholder upgrade task raised: %s", e)
        return
    if not new_phrase or stop.is_set():
        return
    new_base = _strip_trailing_dots(new_phrase) or new_phrase
    base_ref[0] = new_base
    try:
        await bot_message.edit_text(
            f"<i>{html.escape(new_base + '.')}</i>",
            parse_mode=ParseMode.HTML,
        )
    except RetryAfter:
        pass
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.debug("placeholder upgrade BadRequest: %s", e)


async def stream_reply(
    target: Message,
    chunks: AsyncIterator[str],
    *,
    placeholder: str | None = None,
    placeholder_upgrade: Awaitable[str | None] | None = None,
    min_edit_interval: float = _DEFAULT_MIN_INTERVAL,
) -> Message:
    """Send a reply to `target` and progressively fill it with streamed text.

    If `placeholder_upgrade` is given, the random starter is shown immediately
    and replaced in-place once the awaitable resolves to a non-empty string
    (the animation keeps cycling dots with the new base).

    Returns the sent Message (with its final text applied).
    """
    if placeholder is None:
        placeholder = random_phrase()
    base = _strip_trailing_dots(placeholder) or placeholder
    bot_message = await target.reply_text(
        f"<i>{html.escape(base + '.')}</i>",
        parse_mode=ParseMode.HTML,
    )

    base_ref = [base]
    stop_animation = asyncio.Event()
    animation_task = asyncio.create_task(
        _animate_placeholder(bot_message, base_ref, stop_animation)
    )

    upgrade_task: asyncio.Task | None = None
    if placeholder_upgrade is not None:
        upgrade_task = asyncio.create_task(
            _upgrade_placeholder(
                bot_message, base_ref, placeholder_upgrade, stop_animation
            )
        )

    buffer: list[str] = []
    last_edit_at = 0.0
    last_text = ""
    got_anything = False

    async def _stop_animation():
        if not stop_animation.is_set():
            stop_animation.set()
            pending = [t for t in (animation_task, upgrade_task) if t is not None]
            for t in pending:
                try:
                    await t
                except Exception as e:
                    logger.debug("background task ended with: %s", e)

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

    html_text = md_to_html(final_text)
    try:
        await bot_message.edit_text(html_text, parse_mode=ParseMode.HTML)
    except RetryAfter as e:
        await asyncio.sleep(float(e.retry_after))
        try:
            await bot_message.edit_text(html_text, parse_mode=ParseMode.HTML)
        except BadRequest as e2:
            logger.warning("stream final edit retry failed: %s", e2)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return bot_message
        logger.warning("stream HTML edit failed (%s); falling back to plain", e)
        try:
            await bot_message.edit_text(final_text)
        except BadRequest as e2:
            if "not modified" not in str(e2).lower():
                logger.warning("stream plain edit also failed: %s", e2)
    return bot_message


async def edit_with_animated_status(
    target: Message,
    work: Awaitable[T],
    renderer: Callable[[T | Exception], tuple[str, Any, bool]],
    *,
    placeholder: str | None = None,
) -> Message:
    """Send a placeholder reply with animated dots while `work` runs, then
    edit that same message in place with whatever `renderer(result)` returns.

    `renderer` is invoked with either the awaited value or the raised
    Exception, and must return `(text, keyboard, is_html)`. `keyboard` may be
    None or any object exposing `.to_markup()` (e.g. framework `Keyboard`).
    """
    if placeholder is None:
        placeholder = random_phrase()
    base = _strip_trailing_dots(placeholder) or placeholder
    bot_message = await target.reply_text(
        f"<i>{html.escape(base + '.')}</i>",
        parse_mode=ParseMode.HTML,
    )

    base_ref = [base]
    stop_animation = asyncio.Event()
    animation_task = asyncio.create_task(
        _animate_placeholder(bot_message, base_ref, stop_animation)
    )

    result: T | Exception
    try:
        result = await work
    except Exception as e:
        result = e
    finally:
        stop_animation.set()
        try:
            await animation_task
        except Exception as e:
            logger.debug("animation task ended with: %s", e)

    text, keyboard, is_html = renderer(result)
    markup = keyboard.to_markup() if keyboard is not None else None
    parse_mode = ParseMode.HTML if is_html else None
    try:
        await bot_message.edit_text(text, reply_markup=markup, parse_mode=parse_mode)
    except RetryAfter as e:
        await asyncio.sleep(float(e.retry_after))
        try:
            await bot_message.edit_text(text, reply_markup=markup, parse_mode=parse_mode)
        except BadRequest as e2:
            logger.warning("status edit retry failed: %s", e2)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("status edit BadRequest: %s", e)
    return bot_message
