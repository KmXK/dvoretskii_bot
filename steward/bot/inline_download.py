"""Inline-режим: `@бот <ссылка на тикток>` в любом чате (бот там не нужен).

Telegram требует на answerInlineQuery либо публичный URL, либо file_id уже
загруженного файла. Поэтому качаем видео обычным путём, заливаем его в
служебный чат, чтобы получить file_id, удаляем служебное сообщение и отдаём
InlineQueryResultCachedVideo. Если юзер не дождался и query протух — результат
остаётся в кэше, повторный ввод той же ссылки отвечает мгновенно.
"""

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass
from os import environ
from urllib.parse import urlparse
from uuid import uuid4

from telegram import (
    InlineQuery,
    InlineQueryResult,
    InlineQueryResultArticle,
    InlineQueryResultCachedVideo,
    InputFile,
    InputTextMessageContent,
)
from telegram.error import BadRequest
from telegram.ext import ExtBot

from steward.features.download.yt import (
    TIKTOK_FALLBACK_FORMAT,
    TIKTOK_VIDEO_FORMAT,
    URL_REGEX,
    _make_caption,
    download_video_file,
)
from steward.metrics import ContextMetrics

logger = logging.getLogger(__name__)

_CACHE_MAX = 200


@dataclass
class _CachedVideo:
    file_id: str
    caption: str | None


_cache: dict[str, _CachedVideo] = {}
_inflight: dict[str, asyncio.Task] = {}


def find_tiktok_url(text: str) -> str | None:
    for url in re.findall(URL_REGEX, text):
        host = urlparse(url).hostname or ""
        if host == "tiktok.com" or host.endswith(".tiktok.com"):
            return url
    return None


def _upload_chat_id() -> int:
    raw = environ.get("INLINE_UPLOAD_CHAT_ID")
    if raw:
        return int(raw)
    from steward.features.db import DbFeature

    return DbFeature.TARGET_CHAT_ID


async def _download_and_upload(url: str, bot: ExtBot) -> _CachedVideo:
    with tempfile.TemporaryDirectory(prefix="inline_tiktok_") as dir:
        info, filepath = await download_video_file(
            url,
            dir,
            type_name="tiktok",
            video_format=TIKTOK_VIDEO_FORMAT,
            fallback_format=TIKTOK_FALLBACK_FORMAT,
        )

        caption = _make_caption(info)
        width = height = None
        if isinstance(info, dict):
            width = info.get("width")
            height = info.get("height")

        with open(filepath, "rb") as file:
            msg = await bot.send_video(
                _upload_chat_id(),
                InputFile(file, filename="tiktok Video"),
                supports_streaming=True,
                width=int(width) if width else None,
                height=int(height) if height else None,
                caption=caption,
                parse_mode="HTML" if caption else None,
                disable_notification=True,
            )

    if msg.video is None:
        raise RuntimeError(f"служебная загрузка вернула не видео: {msg}")

    try:
        await bot.delete_message(msg.chat_id, msg.message_id)
    except Exception as e:
        logger.warning("не удалось удалить служебное видео: %s", e)

    return _CachedVideo(file_id=msg.video.file_id, caption=caption)


async def _get_video(url: str, bot: ExtBot) -> _CachedVideo:
    if url in _cache:
        return _cache[url]

    # Telegram шлёт inline query на каждое изменение текста — дедупим,
    # чтобы одна ссылка не качалась параллельно несколько раз.
    task = _inflight.get(url)
    if task is None:
        task = asyncio.create_task(_download_and_upload(url, bot))
        _inflight[url] = task
        task.add_done_callback(lambda _: _inflight.pop(url, None))

    video = await task

    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[url] = video
    return video


async def _safe_answer(
    query: InlineQuery,
    results: list[InlineQueryResult],
    *,
    cache_time: int,
) -> None:
    try:
        await query.answer(results, cache_time=cache_time)
    except BadRequest as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            logger.info("inline query протух до ответа: %s", e)
            return
        raise


async def handle_inline_download(
    query: InlineQuery,
    bot: ExtBot,
    metrics: ContextMetrics,
) -> bool:
    """True — запрос распознан как ссылка на тикток и обработан."""
    url = find_tiktok_url(query.query)
    if url is None:
        return False

    try:
        video = await _get_video(url, bot)
    except Exception as e:
        logger.warning("inline-загрузка %s не удалась: %s", url, e)
        await _safe_answer(
            query,
            [
                InlineQueryResultArticle(
                    id=uuid4().hex,
                    title="Не получилось скачать видео",
                    description="Отправится просто ссылка",
                    input_message_content=InputTextMessageContent(url),
                )
            ],
            cache_time=10,
        )
        return True

    metrics.inc("bot_downloads_total", {"download_type": "tiktok_inline"})
    await _safe_answer(
        query,
        [
            InlineQueryResultCachedVideo(
                id=uuid4().hex,
                video_file_id=video.file_id,
                title="Отправить видео",
                caption=video.caption,
                parse_mode="HTML" if video.caption else None,
            )
        ],
        cache_time=3600,
    )
    return True
