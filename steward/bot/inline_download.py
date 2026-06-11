"""Inline-режим: `@бот <ссылка на тикток/инсту>` в любом чате (бот там не нужен).

Telegram требует на answerInlineQuery либо публичный URL, либо file_id уже
загруженного файла. Поэтому качаем медиа обычным путём, заливаем их в
служебный чат, чтобы получить file_id, удаляем служебные сообщения и отдаём
cached-результаты. Если юзер не дождался и query протух — результат остаётся
в кэше, повторный ввод той же ссылки отвечает мгновенно.
"""

import asyncio
import logging
import re
import tempfile
from os import environ
from urllib.parse import urlparse
from uuid import uuid4

from telegram import (
    InlineQuery,
    InlineQueryResult,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InputFile,
    InputTextMessageContent,
    Message,
)
from telegram.error import BadRequest
from telegram.ext import ExtBot

from steward.features.download import video_cache
from steward.features.download.callbacks import download_file
from steward.features.download.video_cache import CachedMedia
from steward.features.download.yt import (
    TIKTOK_FALLBACK_FORMAT,
    TIKTOK_VIDEO_FORMAT,
    URL_REGEX,
    _make_caption,
    download_video_file,
    resolve_instagram_medias,
)
from steward.metrics import ContextMetrics

logger = logging.getLogger(__name__)

_INSTAGRAM_MEDIA_LIMIT = 10

_inflight: dict[str, asyncio.Task] = {}


def find_supported_url(text: str) -> tuple[str, str] | None:
    """(url, kind) первой поддерживаемой ссылки в тексте, либо None."""
    for url in re.findall(URL_REGEX, text):
        host = urlparse(url).hostname or ""
        if host == "tiktok.com" or host.endswith(".tiktok.com"):
            return url, "tiktok"
        if host == "instagram.com" or host.endswith(".instagram.com"):
            return url, "instagram"
    return None


def _upload_chat_id() -> int:
    raw = environ.get("INLINE_UPLOAD_CHAT_ID")
    if raw:
        return int(raw)
    from steward.features.db import DbFeature

    return DbFeature.TARGET_CHAT_ID


async def _delete_quietly(bot: ExtBot, msg: Message) -> None:
    try:
        await bot.delete_message(msg.chat_id, msg.message_id)
    except Exception as e:
        logger.warning("не удалось удалить служебное сообщение: %s", e)


async def _upload_tiktok(url: str, bot: ExtBot) -> list[CachedMedia]:
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
        raise RuntimeError("служебная загрузка вернула не видео")

    await _delete_quietly(bot, msg)
    return [CachedMedia(file_id=msg.video.file_id, caption=caption)]


async def _upload_instagram(url: str, bot: ExtBot) -> list[CachedMedia]:
    medias = await resolve_instagram_medias(url)
    if not medias:
        raise RuntimeError("инста не отдала ни одного медиа")
    medias = medias[:_INSTAGRAM_MEDIA_LIMIT]
    chat_id = _upload_chat_id()

    async def upload_one(media_url: str, is_video: bool) -> CachedMedia:
        async with download_file(media_url, use_proxy=True) as file:
            if is_video:
                msg = await bot.send_video(
                    chat_id,
                    file,
                    supports_streaming=True,
                    disable_notification=True,
                )
                file_id = msg.video.file_id if msg.video else None
            else:
                msg = await bot.send_photo(
                    chat_id,
                    file,
                    disable_notification=True,
                )
                file_id = msg.photo[-1].file_id if msg.photo else None
        if file_id is None:
            raise RuntimeError("служебная загрузка вернула не видео/фото")
        await _delete_quietly(bot, msg)
        return CachedMedia(file_id=file_id, caption=None, is_video=is_video)

    return list(await asyncio.gather(*[upload_one(u, v) for u, v in medias]))


async def _get_medias(url: str, kind: str, bot: ExtBot) -> list[CachedMedia]:
    cached = video_cache.get(url)
    if cached is not None:
        return cached

    # Telegram шлёт inline query на каждое изменение текста — дедупим,
    # чтобы одна ссылка не качалась параллельно несколько раз.
    task = _inflight.get(url)
    if task is None:
        upload = _upload_tiktok if kind == "tiktok" else _upload_instagram
        task = asyncio.create_task(upload(url, bot))
        _inflight[url] = task
        task.add_done_callback(lambda _: _inflight.pop(url, None))

    medias = await task
    video_cache.put(url, medias)
    return medias


def _to_results(medias: list[CachedMedia]) -> list[InlineQueryResult]:
    results: list[InlineQueryResult] = []
    for m in medias:
        if m.is_video:
            results.append(InlineQueryResultCachedVideo(
                id=uuid4().hex,
                video_file_id=m.file_id,
                title="Отправить видео",
                caption=m.caption,
                parse_mode="HTML" if m.caption else None,
            ))
        else:
            results.append(InlineQueryResultCachedPhoto(
                id=uuid4().hex,
                photo_file_id=m.file_id,
                caption=m.caption,
                parse_mode="HTML" if m.caption else None,
            ))
    return results


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
    """True — запрос распознан как поддерживаемая ссылка и обработан."""
    found = find_supported_url(query.query)
    if found is None:
        return False
    url, kind = found

    try:
        medias = await _get_medias(url, kind, bot)
    except Exception as e:
        logger.warning("inline-загрузка %s не удалась: %s", url, e)
        error_text = f"{type(e).__name__}: {e}".replace("\n", " ")
        await _safe_answer(
            query,
            [
                InlineQueryResultArticle(
                    id=uuid4().hex,
                    title="❌ Не получилось скачать",
                    description=error_text[:150],
                    input_message_content=InputTextMessageContent(url),
                )
            ],
            cache_time=10,
        )
        return True

    metrics.inc("bot_downloads_total", {"download_type": f"{kind}_inline"})
    await _safe_answer(query, _to_results(medias), cache_time=3600)
    return True
