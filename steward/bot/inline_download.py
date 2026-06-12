"""Inline-режим: `@бот <текст со ссылкой>` в любом чате (бот там не нужен).

Поддерживаются те же хосты, что и в чатовом DownloadFeature — парсинг ссылок
общий (find_download_urls). Telegram требует на answerInlineQuery либо
публичный URL, либо file_id уже загруженного файла, поэтому качаем медиа
обычным путём, заливаем их в служебный чат, чтобы получить file_id, удаляем
служебные сообщения и отдаём cached-результаты. Если юзер не дождался и query
протух — результат остаётся в кэше, повторный ввод той же ссылки отвечает
мгновенно.

Транскрибация: короткие (< 2 мин) тиктоки после отправки получают
саммари+расшифровку стримингом в caption. Работает через chosen_inline_result
(нужен включённый inline feedback в BotFather) — inline_message_id приходит
только у сообщений с inline-клавиатурой, поэтому на видео висит кнопка
«Источник».
"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from functools import partial
from os import environ
from pathlib import Path
from uuid import uuid4

from pyrate_limiter import BucketFullException
from telegram import (
    ChosenInlineResult,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResult,
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InputFile,
    InputTextMessageContent,
    Message,
)
from telegram.error import BadRequest
from telegram.ext import ExtBot

from steward.data.repository import Repository
from steward.features.download import video_cache
from steward.features.download.callbacks import download_file
from steward.features.download.video_cache import CachedMedia
from steward.features.download.yt import (
    _TIKTOK_AUTO_LIMIT,
    TIKTOK_FALLBACK_FORMAT,
    TIKTOK_VIDEO_FORMAT,
    _make_caption,
    download_image_files,
    download_video_file,
    download_yandex_audio,
    find_download_urls,
    resolve_instagram_medias,
)
from steward.features.voice_video.transcription import create_transcription_reply
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.media import fetch_tg_file_to
from steward.metrics import ContextMetrics

logger = logging.getLogger(__name__)

_MEDIA_LIMIT = 10
_TRANSCRIBE_MAX_DURATION_SEC = 2 * 60
_CHOSEN_CTX_MAX = 500
_EXISTING_CAPTION_KEEP_LIMIT = 250

_inflight: dict[str, asyncio.Task] = {}


def find_supported_url(text: str) -> tuple[str, str] | None:
    """(url, dispatch_key) первой поддерживаемой ссылки в тексте, либо None."""
    found = find_download_urls(text)
    return found[0] if found else None


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


# ── Загрузчики: url -> залитые в Telegram медиа ──────────────────────────────


async def _upload_video(
    url: str,
    bot: ExtBot,
    video_format: str = "(bv+ba)/best",
    fallback_format: str | None = None,
) -> list[CachedMedia]:
    with tempfile.TemporaryDirectory(prefix="inline_video_") as dir:
        info, filepath = await download_video_file(
            url,
            dir,
            type_name="inline",
            video_format=video_format,
            fallback_format=fallback_format,
        )

        caption = _make_caption(info)
        width = height = duration = None
        if isinstance(info, dict):
            width = info.get("width")
            height = info.get("height")
            duration = info.get("duration")

        with open(filepath, "rb") as file:
            msg = await bot.send_video(
                _upload_chat_id(),
                InputFile(file, filename="inline Video"),
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
    return [CachedMedia(
        file_id=msg.video.file_id,
        caption=caption,
        kind="video",
        duration=float(duration) if duration else None,
    )]


async def _upload_images(url: str, bot: ExtBot) -> list[CachedMedia]:
    with tempfile.TemporaryDirectory(prefix="inline_images_") as dir:
        images, audios = await download_image_files(url, dir)
        if not images and not audios:
            raise RuntimeError("gallery-dl не нашёл медиа")
        chat_id = _upload_chat_id()

        async def upload_photo(path: str) -> CachedMedia:
            with open(path, "rb") as file:
                msg = await bot.send_photo(chat_id, file, disable_notification=True)
            if not msg.photo:
                raise RuntimeError("служебная загрузка вернула не фото")
            await _delete_quietly(bot, msg)
            return CachedMedia(file_id=msg.photo[-1].file_id, kind="photo")

        async def upload_audio(path: str) -> CachedMedia:
            with open(path, "rb") as file:
                msg = await bot.send_audio(chat_id, file, disable_notification=True)
            if msg.audio is None:
                raise RuntimeError("служебная загрузка вернула не аудио")
            await _delete_quietly(bot, msg)
            return CachedMedia(file_id=msg.audio.file_id, kind="audio")

        tasks = [upload_photo(p) for p in images[:_MEDIA_LIMIT]]
        tasks += [upload_audio(p) for p in audios[:1]]
        return list(await asyncio.gather(*tasks))


async def _upload_instagram(url: str, bot: ExtBot) -> list[CachedMedia]:
    medias = await resolve_instagram_medias(url)
    if not medias:
        raise RuntimeError("инста не отдала ни одного медиа")
    medias = medias[:_MEDIA_LIMIT]
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
                duration = float(msg.video.duration) if msg.video else None
            else:
                msg = await bot.send_photo(chat_id, file, disable_notification=True)
                file_id = msg.photo[-1].file_id if msg.photo else None
                duration = None
        if file_id is None:
            raise RuntimeError("служебная загрузка вернула не видео/фото")
        await _delete_quietly(bot, msg)
        return CachedMedia(
            file_id=file_id,
            kind="video" if is_video else "photo",
            duration=duration,
        )

    return list(await asyncio.gather(*[upload_one(u, v) for u, v in medias]))


async def _upload_yandex_audio(url: str, bot: ExtBot) -> list[CachedMedia]:
    with tempfile.TemporaryDirectory(prefix="inline_ym_") as dir:
        filepath = await download_yandex_audio(url, dir)
        with open(filepath, "rb") as file:
            msg = await bot.send_audio(
                _upload_chat_id(),
                file,
                filename=Path(filepath).name,
                disable_notification=True,
            )

    if msg.audio is None:
        raise RuntimeError("служебная загрузка вернула не аудио")

    await _delete_quietly(bot, msg)
    return [CachedMedia(file_id=msg.audio.file_id, kind="audio")]


# Зеркало build_dispatch из yt.py: на ключ — цепочка загрузчиков,
# первый успешный побеждает.
_PLANS = {
    "tiktok": [
        partial(
            _upload_video,
            video_format=TIKTOK_VIDEO_FORMAT,
            fallback_format=TIKTOK_FALLBACK_FORMAT,
        ),
        _upload_images,
    ],
    "instagram.com": [_upload_instagram],
    "youtube.com": [_upload_video],
    "youtu.be": [_upload_video],
    "pinterest.com": [_upload_video, _upload_images],
    "pin.it": [_upload_video, _upload_images],
    "music.yandex": [_upload_yandex_audio],
}


async def _load_medias(url: str, key: str, bot: ExtBot) -> list[CachedMedia]:
    last_error: Exception | None = None
    for loader in _PLANS[key]:
        try:
            return await loader(url, bot)
        except Exception as e:
            logger.exception(e)
            last_error = e
    raise last_error or RuntimeError("нет загрузчика")


async def _get_medias(url: str, key: str, bot: ExtBot) -> list[CachedMedia]:
    cached = video_cache.get(url)
    if cached is not None:
        return cached

    # Telegram шлёт inline query на каждое изменение текста — дедупим,
    # чтобы одна ссылка не качалась параллельно несколько раз.
    task = _inflight.get(url)
    if task is None:
        task = asyncio.create_task(_load_medias(url, key, bot))
        _inflight[url] = task
        task.add_done_callback(lambda _: _inflight.pop(url, None))

    medias = await task
    video_cache.put(url, medias)
    return medias


# ── Результаты + контекст для chosen_inline_result ───────────────────────────


@dataclass
class _ChosenCtx:
    url: str
    file_id: str
    caption: str | None


_chosen_ctx: dict[str, _ChosenCtx] = {}


def _source_markup(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Источник", url=url)]])


def _to_results(
    medias: list[CachedMedia],
    url: str,
    key: str,
) -> list[InlineQueryResult]:
    results: list[InlineQueryResult] = []
    for m in medias:
        rid = uuid4().hex
        if m.kind == "video":
            results.append(InlineQueryResultCachedVideo(
                id=rid,
                video_file_id=m.file_id,
                title="Отправить видео",
                caption=m.caption,
                parse_mode="HTML" if m.caption else None,
                reply_markup=_source_markup(url),
            ))
            if (
                key == "tiktok"
                and m.duration is not None
                and m.duration <= _TRANSCRIBE_MAX_DURATION_SEC
            ):
                if len(_chosen_ctx) >= _CHOSEN_CTX_MAX:
                    _chosen_ctx.pop(next(iter(_chosen_ctx)))
                _chosen_ctx[rid] = _ChosenCtx(
                    url=url, file_id=m.file_id, caption=m.caption
                )
        elif m.kind == "photo":
            results.append(InlineQueryResultCachedPhoto(
                id=rid,
                photo_file_id=m.file_id,
                caption=m.caption,
                parse_mode="HTML" if m.caption else None,
            ))
        else:
            results.append(InlineQueryResultCachedAudio(
                id=rid,
                audio_file_id=m.file_id,
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
    url, key = found

    try:
        medias = await _get_medias(url, key, bot)
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

    metrics.inc("bot_downloads_total", {"download_type": f"{key}_inline"})
    await _safe_answer(query, _to_results(medias, url, key), cache_time=3600)
    return True


# ── Транскрибация выбранного видео (chosen_inline_result) ────────────────────


class _InlineCaptionMessage:
    """Message-подобный адаптер: create_transcription_reply умеет стримить
    саммари в caption через .edit_caption — здесь это редактирование
    inline-сообщения по inline_message_id."""

    def __init__(
        self,
        bot: ExtBot,
        inline_message_id: str,
        reply_markup: InlineKeyboardMarkup | None,
    ):
        self._bot = bot
        self._inline_message_id = inline_message_id
        self._reply_markup = reply_markup

    async def edit_caption(self, caption: str, parse_mode: str | None = None):
        await self._bot.edit_message_caption(
            inline_message_id=self._inline_message_id,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=self._reply_markup,
        )


async def handle_chosen_inline_result(
    chosen: ChosenInlineResult,
    bot: ExtBot,
    repository: Repository,
) -> bool:
    """Авто-расшифровка выбранного короткого тиктока стримингом в caption."""
    ctx = _chosen_ctx.pop(chosen.result_id, None)
    if ctx is None or not chosen.inline_message_id:
        return False

    try:
        check_limit(_TIKTOK_AUTO_LIMIT, 2, Duration.MINUTE)
    except BucketFullException:
        logger.info("inline auto-transcribe rate-limited")
        return False

    logger.info("inline транскрибация для %s", ctx.url)
    with tempfile.TemporaryDirectory(prefix="inline_trans_") as dir:
        video_path = Path(dir) / "video.mp4"
        await fetch_tg_file_to(bot, ctx.file_id, video_path)

        adapter = _InlineCaptionMessage(
            bot, chosen.inline_message_id, _source_markup(ctx.url)
        )
        # Длинное описание не оставляем — иначе расшифровке не хватит места
        # в caption и create_transcription_reply уйдёт в reply-флоу, которого
        # у inline-сообщений нет.
        existing = (
            ctx.caption
            if ctx.caption and len(ctx.caption) <= _EXISTING_CAPTION_KEEP_LIMIT
            else ""
        )
        await create_transcription_reply(
            repository,
            adapter,
            video_path,
            speaker_user_id=None,
            speaker_username=None,
            speaker_fallback_name=None,
            speaker_first_name=None,
            caption_message=adapter,
            existing_caption_html=existing,
        )
    return True
