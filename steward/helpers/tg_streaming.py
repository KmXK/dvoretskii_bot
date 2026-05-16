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
import inspect
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

from telegram import Message
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, RetryAfter

from steward.helpers.md_to_html import md_to_html
from steward.helpers.thinking import random_phrase

T = TypeVar("T")

logger = logging.getLogger(__name__)

_DEFAULT_MIN_INTERVAL = 1.5  # seconds between edits during streaming
_TYPING_REFRESH = 4.0  # seconds between chat-action pings (TG expires after ~5s)
_TG_TEXT_LIMIT = 4096
_PLACEHOLDER_SUFFIX = "…"


def _strip_trailing_dots(text: str) -> str:
    return text.rstrip("…").rstrip(".").rstrip()


async def _typing_progress(bot_message: Message, stop: asyncio.Event) -> None:
    """Keep a 'typing…' chat action alive until `stop` is set.

    Telegram's chat-action API is the canonical way to signal a long-running
    operation: each call expires after ~5s, so we refresh every 4s. Unlike
    `editMessageText`, it's not subject to per-message flood limits.
    """
    bot = bot_message.get_bot()
    chat_id = bot_message.chat_id
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except RetryAfter as e:
            try:
                await asyncio.wait_for(stop.wait(), timeout=float(e.retry_after))
                return
            except asyncio.TimeoutError:
                continue
        except Exception as e:
            logger.debug("typing chat action failed: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=_TYPING_REFRESH)
            return
        except asyncio.TimeoutError:
            pass


async def _upgrade_placeholder(
    bot_message: Message,
    upgrade: Awaitable[str | None],
    stop: asyncio.Event,
) -> None:
    """Wait for a contextual placeholder; on arrival, edit the message once."""
    try:
        new_phrase = await upgrade
    except Exception as e:
        logger.debug("placeholder upgrade task raised: %s", e)
        return
    if not new_phrase or stop.is_set():
        return
    new_base = _strip_trailing_dots(new_phrase) or new_phrase
    try:
        await bot_message.edit_text(
            f"<i>{html.escape(new_base + _PLACEHOLDER_SUFFIX)}</i>",
            parse_mode=ParseMode.HTML,
        )
    except RetryAfter:
        pass
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.debug("placeholder upgrade BadRequest: %s", e)


async def stream_reply(
    target: Message,
    chunks: AsyncIterator[str] | Awaitable[AsyncIterator[str]],
    *,
    placeholder: str | None = None,
    placeholder_upgrade: Awaitable[str | None] | None = None,
    min_edit_interval: float = _DEFAULT_MIN_INTERVAL,
) -> Message:
    """Send a reply to `target` and progressively fill it with streamed text.

    `chunks` can be either an AsyncIterator (ready to iterate) or an Awaitable
    that resolves to one — in the latter case the placeholder is sent FIRST
    and the resolution happens after, so the user gets immediate feedback even
    when stream initialization is slow.

    If `placeholder_upgrade` is given, the random starter is shown immediately
    and replaced in-place once the awaitable resolves to a non-empty string
    (the animation keeps cycling dots with the new base).

    Returns the sent Message (with its final text applied).
    """
    if placeholder is None:
        placeholder = random_phrase()
    base = _strip_trailing_dots(placeholder) or placeholder
    bot_message = await target.reply_text(
        f"<i>{html.escape(base + _PLACEHOLDER_SUFFIX)}</i>",
        parse_mode=ParseMode.HTML,
    )

    stop_animation = asyncio.Event()
    animation_task = asyncio.create_task(
        _typing_progress(bot_message, stop_animation)
    )

    upgrade_task: asyncio.Task | None = None
    if placeholder_upgrade is not None:
        upgrade_task = asyncio.create_task(
            _upgrade_placeholder(bot_message, placeholder_upgrade, stop_animation)
        )

    if inspect.isawaitable(chunks):
        try:
            chunks = await chunks
        except Exception:
            stop_animation.set()
            try:
                await animation_task
            except Exception:
                pass
            if upgrade_task is not None:
                upgrade_task.cancel()
            raise

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

    try:
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
                if "not modified" not in str(e).lower():
                    logger.warning("stream edit BadRequest: %s", e)
    except Exception as stream_err:
        logger.warning("stream_reply: stream raised: %s", stream_err)
        if not got_anything:
            try:
                await bot_message.edit_text("⚠️ Что-то пошло не так, попробуй ещё раз")
            except Exception:
                pass
        raise
    finally:
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
        f"<i>{html.escape(base + _PLACEHOLDER_SUFFIX)}</i>",
        parse_mode=ParseMode.HTML,
    )

    stop_animation = asyncio.Event()
    animation_task = asyncio.create_task(
        _typing_progress(bot_message, stop_animation)
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
