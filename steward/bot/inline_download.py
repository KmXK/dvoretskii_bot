"""Inline-режим: `@бот <текст со ссылкой>` в любом чате (бот там не нужен).

Поддерживаются те же хосты, что и в чатовом DownloadFeature — парсинг ссылок
общий (find_download_urls). Telegram требует на answerInlineQuery либо
публичный URL, либо file_id уже загруженного файла, поэтому качаем медиа
обычным путём, заливаем их в служебный чат, чтобы получить file_id, удаляем
служебные сообщения и отдаём cached-результаты. Долгая загрузка возвращает
отправляемый placeholder: после выбора он сам заменяется готовым медиа, а
повторный ввод прогретой ссылки отвечает мгновенно.

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
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pyrate_limiter import BucketFullException
from telegram import (
    CallbackQuery,
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
    InputMediaAudio,
    InputMediaPhoto,
    InputMediaVideo,
    InputTextMessageContent,
    Message,
)
from telegram.error import BadRequest
from telegram.ext import ExtBot

from steward.data.repository import Repository
from steward.features.download import video_cache
from steward.features.download.callbacks import (
    REMOTE_MEDIA_TOTAL_LIMIT,
    DownloadBudget,
    download_file,
    enter_download_contexts,
)
from steward.features.download.image_description import (
    append_image_description,
    describe_image_files,
)
from steward.features.download.video_cache import CachedMedia
from steward.features.download.yt import (
    _TIKTOK_AUTO_LIMIT,
    _IMAGE_POST_CAPTION_LIMIT,
    THREADS_MEDIA_HEADERS,
    TIKTOK_FALLBACK_FORMAT,
    TIKTOK_VIDEO_FORMAT,
    _extract_info_only,
    _gallery_audio_filename,
    _make_caption,
    download_image_files,
    download_video_file,
    download_yandex_audio,
    find_download_urls,
    resolve_instagram_medias,
    resolve_threads_medias,
)
from steward.features.voice_video.transcription import create_transcription_reply
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.media import fetch_tg_file_to, is_video_file
from steward.metrics import ContextMetrics

logger = logging.getLogger(__name__)

_MEDIA_LIMIT = 10
_TRANSCRIBE_MAX_DURATION_SEC = 2 * 60
_CHOSEN_CTX_MAX = 500
_EXISTING_CAPTION_KEEP_LIMIT = 250
_INLINE_QUERY_WAIT_SECONDS = 3
_PENDING_CTX_MAX = 500
_PENDING_CALLBACK_PREFIX = "inline:pending|"
_QUERYLESS_CACHE_KEYS = frozenset({"instagram.com", "threads.com", "threads.net"})

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
        images, audios, metadata = await download_image_files(url, dir)
        if not images and not audios:
            raise RuntimeError("gallery-dl не нашёл медиа")
        chat_id = _upload_chat_id()
        description = await describe_image_files(
            [Path(path) for path in images if not is_video_file(path)]
        )
        caption = append_image_description(
            _make_caption(metadata, _IMAGE_POST_CAPTION_LIMIT),
            description,
        )

        async def upload_media(path: str) -> CachedMedia:
            is_video = is_video_file(path)
            with open(path, "rb") as file:
                if is_video:
                    msg = await bot.send_video(
                        chat_id,
                        file,
                        supports_streaming=True,
                        disable_notification=True,
                    )
                else:
                    msg = await bot.send_photo(
                        chat_id,
                        file,
                        disable_notification=True,
                    )

            if is_video:
                if msg.video is None:
                    raise RuntimeError("служебная загрузка вернула не видео")
                media = CachedMedia(
                    file_id=msg.video.file_id,
                    kind="video",
                    caption=caption,
                )
            else:
                if not msg.photo:
                    raise RuntimeError("служебная загрузка вернула не фото")
                media = CachedMedia(
                    file_id=msg.photo[-1].file_id,
                    kind="photo",
                    caption=caption,
                )

            await _delete_quietly(bot, msg)
            return media

        async def upload_audio(path: str) -> CachedMedia:
            filename = _gallery_audio_filename(metadata, path)
            with open(path, "rb") as file:
                msg = await bot.send_audio(
                    chat_id,
                    file,
                    filename=filename,
                    disable_notification=True,
                )
            if msg.audio is None:
                raise RuntimeError("служебная загрузка вернула не аудио")
            await _delete_quietly(bot, msg)
            return CachedMedia(
                file_id=msg.audio.file_id,
                kind="audio",
                title=Path(filename).stem,
            )

        tasks = [upload_media(p) for p in images[:_MEDIA_LIMIT]]
        tasks += [upload_audio(p) for p in audios[:1]]
        return list(await asyncio.gather(*tasks))


async def _upload_resolved_medias(
    medias: list[tuple[str, bool]],
    metadata: Any,
    bot: ExtBot,
    request_headers: dict[str, str] | None = None,
) -> list[CachedMedia]:
    medias = medias[:_MEDIA_LIMIT]
    chat_id = _upload_chat_id()
    budget = DownloadBudget(REMOTE_MEDIA_TOTAL_LIMIT)
    contexts = [
        download_file(
            media_url,
            use_proxy=True,
            request_headers=request_headers,
            budget=budget,
        )
        for media_url, _ in medias
    ]
    try:
        results = await enter_download_contexts(
            contexts,
        )
        exceptions = [result for result in results if isinstance(result, BaseException)]
        if exceptions:
            raise ExceptionGroup("", exceptions)

        files = [result for result in results if not isinstance(result, BaseException)]
        description = await describe_image_files(
            [
                Path(file.name)
                for file, (_, is_video) in zip(files, medias)
                if not is_video
            ]
        )
        caption = append_image_description(
            _make_caption(metadata, _IMAGE_POST_CAPTION_LIMIT),
            description,
        )

        async def upload_one(file, is_video: bool) -> CachedMedia:
            file.seek(0)
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
                caption=caption,
                duration=duration,
            )

        return list(await asyncio.gather(*[
            upload_one(file, is_video)
            for file, (_, is_video) in zip(files, medias)
        ]))
    finally:
        await asyncio.gather(
            *[
                context.__aexit__(None, None, None)
                for context in contexts
            ],
            return_exceptions=True,
        )


async def _upload_instagram(url: str, bot: ExtBot) -> list[CachedMedia]:
    meta_task = asyncio.create_task(_extract_info_only(url))
    try:
        medias = await resolve_instagram_medias(url)
    except BaseException:
        meta_task.cancel()
        raise

    if not medias:
        meta_task.cancel()
        raise RuntimeError("инста не отдала ни одного медиа")

    return await _upload_resolved_medias(
        medias,
        await meta_task,
        bot,
    )


async def _upload_threads(url: str, bot: ExtBot) -> list[CachedMedia]:
    medias, metadata = await resolve_threads_medias(url)
    return await _upload_resolved_medias(
        medias,
        metadata,
        bot,
        THREADS_MEDIA_HEADERS,
    )


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
    return [CachedMedia(
        file_id=msg.audio.file_id,
        kind="audio",
        title=Path(filepath).stem,
    )]


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
    "threads.com": [_upload_threads],
    "threads.net": [_upload_threads],
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


def _media_cache_key(url: str, key: str) -> str:
    if key not in _QUERYLESS_CACHE_KEYS:
        return url

    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, "", ""))


async def _get_medias(url: str, key: str, bot: ExtBot) -> list[CachedMedia]:
    cache_key = _media_cache_key(url, key)
    cached = video_cache.get(cache_key) or video_cache.get(url)
    if cached is not None:
        return cached

    # Telegram шлёт inline query на каждое изменение текста — дедупим,
    # чтобы одна ссылка не качалась параллельно несколько раз.
    task = _inflight.get(cache_key)
    if task is None:
        task = asyncio.create_task(_load_medias(url, key, bot))
        _inflight[cache_key] = task
        task.add_done_callback(lambda _: _inflight.pop(cache_key, None))

    medias = await task
    video_cache.put(cache_key, medias)
    return medias


# ── Результаты + контекст для chosen_inline_result ───────────────────────────


@dataclass
class _ChosenCtx:
    url: str
    file_id: str
    caption: str | None


@dataclass
class _PendingCtx:
    url: str
    task: asyncio.Task[list[CachedMedia]]
    chat_type: str | None = None
    delivery_task: asyncio.Task[None] | None = None


_chosen_ctx: dict[str, _ChosenCtx] = {}
_pending_ctx: dict[str, _PendingCtx] = {}


def _source_markup(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Источник", url=url)]])


def _pending_markup(url: str, result_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⏳ Дождаться",
            callback_data=f"{_PENDING_CALLBACK_PREFIX}{result_id}",
        )],
        [InlineKeyboardButton("Источник", url=url)],
    ])


def _ready_markup(
    url: str,
    media_count: int,
    chat_type: str | None,
) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton("Источник", url=url)]
    if media_count > 1 and chat_type != "channel":
        found = find_supported_url(url)
        query_url = _media_cache_key(url, found[1]) if found else url
        remaining_button = InlineKeyboardButton(
            f"Остальные ({media_count - 1})",
            switch_inline_query_current_chat=query_url,
        )
        buttons.append(remaining_button)

    return InlineKeyboardMarkup([buttons])


def _pending_result(
    url: str,
    task: asyncio.Task[list[CachedMedia]],
    chat_type: str | None,
) -> InlineQueryResultArticle:
    result_id = uuid4().hex
    if len(_pending_ctx) >= _PENDING_CTX_MAX:
        _pending_ctx.pop(next(iter(_pending_ctx)))

    _pending_ctx[result_id] = _PendingCtx(
        url=url,
        task=task,
        chat_type=chat_type,
    )
    return InlineQueryResultArticle(
        id=result_id,
        title="⏳ Догружаю — можно отправлять",
        description="Сообщение само заменится готовым медиа",
        input_message_content=InputTextMessageContent(
            "⏳ Загружаю медиа…"
        ),
        reply_markup=_pending_markup(url, result_id),
    )


def _record_background_result(
    task: asyncio.Task[list[CachedMedia]],
    *,
    url: str,
    key: str,
    metrics: ContextMetrics,
) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as error:
        logger.warning("фоновая inline-загрузка %s не удалась: %s", url, error)
        return

    metrics.inc("bot_downloads_total", {"download_type": f"{key}_inline"})


def _watch_background_result(
    task: asyncio.Task[list[CachedMedia]],
    url: str,
    key: str,
    metrics: ContextMetrics,
) -> None:
    task.add_done_callback(
        partial(
            _record_background_result,
            url=url,
            key=key,
            metrics=metrics,
        )
    )


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
                title=m.title or "Отправить аудио",
                caption=m.caption,
                parse_mode="HTML" if m.caption else None,
            ))
    return results


async def _safe_answer(
    query: InlineQuery,
    results: list[InlineQueryResult],
    *,
    cache_time: int,
    is_personal: bool = True,
) -> bool:
    try:
        await query.answer(
            results,
            cache_time=cache_time,
            is_personal=is_personal,
        )
        return True
    except BadRequest as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            logger.info("inline query протух до ответа: %s", e)
            return False
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

    media_task = asyncio.create_task(_get_medias(url, key, bot))
    try:
        done, _ = await asyncio.wait(
            {media_task},
            timeout=_INLINE_QUERY_WAIT_SECONDS,
        )
    except asyncio.CancelledError:
        _watch_background_result(
            media_task,
            url,
            key,
            metrics,
        )
        raise

    if media_task not in done:
        logger.info(
            "inline-загрузка %s продолжается в фоне после %s секунд",
            url,
            _INLINE_QUERY_WAIT_SECONDS,
        )
        _watch_background_result(
            media_task,
            url,
            key,
            metrics,
        )
        pending_result = _pending_result(
            url,
            media_task,
            query.chat_type,
        )
        try:
            answered = await _safe_answer(
                query,
                [pending_result],
                cache_time=0,
            )
        except BaseException:
            _pending_ctx.pop(pending_result.id, None)
            raise

        if not answered:
            _pending_ctx.pop(pending_result.id, None)

        return True

    try:
        medias = media_task.result()
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


async def _finish_pending_result(
    pending: _PendingCtx,
    inline_message_id: str,
    bot: ExtBot,
) -> None:
    try:
        medias = await asyncio.shield(pending.task)
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}".replace("\n", " ")
        await bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=f"❌ Не получилось скачать\n{error_text[:300]}",
            reply_markup=_source_markup(pending.url),
        )
        return

    if not medias:
        await bot.edit_message_text(
            inline_message_id=inline_message_id,
            text="❌ Загрузчик не вернул медиа",
            reply_markup=_source_markup(pending.url),
        )
        return

    media = medias[0]
    parse_mode = "HTML" if media.caption else None
    if media.kind == "photo":
        input_media = InputMediaPhoto(
            media.file_id,
            caption=media.caption,
            parse_mode=parse_mode,
        )
    elif media.kind == "audio":
        input_media = InputMediaAudio(
            media.file_id,
            caption=media.caption,
            parse_mode=parse_mode,
        )
    else:
        input_media = InputMediaVideo(
            media.file_id,
            caption=media.caption,
            parse_mode=parse_mode,
            supports_streaming=True,
        )

    await bot.edit_message_media(
        inline_message_id=inline_message_id,
        media=input_media,
        reply_markup=_ready_markup(
            pending.url,
            len(medias),
            pending.chat_type,
        ),
    )


def _record_pending_delivery(
    task: asyncio.Task[None],
    *,
    result_id: str,
    pending: _PendingCtx,
) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        if pending.delivery_task is task:
            pending.delivery_task = None
        return
    except Exception as error:
        if pending.delivery_task is task:
            pending.delivery_task = None
        logger.warning("не удалось доставить inline-медиа: %s", error)
        return

    if _pending_ctx.get(result_id) is pending:
        _pending_ctx.pop(result_id, None)


async def _deliver_pending_result(
    result_id: str,
    pending: _PendingCtx,
    inline_message_id: str,
    bot: ExtBot,
) -> None:
    delivery_task = pending.delivery_task
    if delivery_task is None:
        delivery_task = asyncio.create_task(
            _finish_pending_result(
                pending,
                inline_message_id,
                bot,
            )
        )
        pending.delivery_task = delivery_task
        delivery_task.add_done_callback(
            partial(
                _record_pending_delivery,
                result_id=result_id,
                pending=pending,
            )
        )

    try:
        await asyncio.shield(delivery_task)
    except Exception:
        if pending.delivery_task is delivery_task:
            pending.delivery_task = None
        raise

    if _pending_ctx.get(result_id) is pending:
        _pending_ctx.pop(result_id, None)


async def handle_pending_inline_callback(
    callback: CallbackQuery,
    bot: ExtBot,
) -> bool:
    data = callback.data
    if not isinstance(data, str) or not data.startswith(_PENDING_CALLBACK_PREFIX):
        return False

    result_id = data.removeprefix(_PENDING_CALLBACK_PREFIX)
    pending = _pending_ctx.get(result_id)
    if pending is None:
        await callback.answer("Уже обработано")
        return True

    if not callback.inline_message_id:
        await callback.answer(
            "Не могу обновить это сообщение",
            show_alert=True,
        )
        return True

    try:
        await callback.answer("Догружаю…")
    except Exception as error:
        logger.warning("не удалось ответить на inline callback: %s", error)

    await _deliver_pending_result(
        result_id,
        pending,
        callback.inline_message_id,
        bot,
    )
    return True


async def handle_chosen_inline_result(
    chosen: ChosenInlineResult,
    bot: ExtBot,
    repository: Repository,
) -> bool:
    """Обработка выбранного отложенного результата или транскрибации."""
    pending = _pending_ctx.get(chosen.result_id)
    if pending is not None:
        if not chosen.inline_message_id:
            return False

        logger.info("выбран отложенный inline-результат для %s", pending.url)
        await _deliver_pending_result(
            chosen.result_id,
            pending,
            chosen.inline_message_id,
            bot,
        )
        return True

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
