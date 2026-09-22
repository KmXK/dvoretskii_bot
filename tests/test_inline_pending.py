import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import (
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InputMediaAudio,
    InputMediaPhoto,
    InputMediaVideo,
)
from telegram.error import BadRequest

import steward.bot.inline_download as inline_download
from steward.bot.bot import Bot
from steward.features.download import video_cache
from steward.features.download.video_cache import CachedMedia


@pytest.fixture(autouse=True)
def clear_inline_state():
    inline_download._chosen_ctx.clear()
    inline_download._pending_ctx.clear()
    inline_download._inflight.clear()
    video_cache._cache.clear()
    yield
    inline_download._chosen_ctx.clear()
    inline_download._pending_ctx.clear()
    inline_download._inflight.clear()
    video_cache._cache.clear()


def _query(url: str):
    query = MagicMock()
    query.query = url
    query.chat_type = "private"
    query.answer = AsyncMock(return_value=True)
    return query


def _chosen(result_id: str, inline_message_id: str | None = "inline-message"):
    chosen = MagicMock()
    chosen.result_id = result_id
    chosen.inline_message_id = inline_message_id
    return chosen


def _callback(result_id: str, inline_message_id: str | None = "inline-message"):
    callback = MagicMock()
    callback.data = f"{inline_download._PENDING_CALLBACK_PREFIX}{result_id}"
    callback.inline_message_id = inline_message_id
    callback.answer = AsyncMock()
    return callback


async def test_safe_answer_is_personal():
    query = _query("query")

    answered = await inline_download._safe_answer(
        query,
        [],
        cache_time=60,
    )

    assert answered is True
    query.answer.assert_awaited_once_with(
        [],
        cache_time=60,
        is_personal=True,
    )


async def test_safe_answer_reports_expired_query():
    query = _query("query")
    query.answer.side_effect = BadRequest(
        "Query is too old and response timeout expired or query id is invalid"
    )

    answered = await inline_download._safe_answer(
        query,
        [],
        cache_time=0,
    )

    assert answered is False


async def test_fast_inline_download_returns_media(monkeypatch):
    url = "https://www.threads.com/@author/post/Fast123"
    media = CachedMedia(
        file_id="photo-file",
        caption="Описание",
        kind="photo",
    )
    get_medias = AsyncMock(return_value=[media])
    monkeypatch.setattr(inline_download, "_get_medias", get_medias)
    query = _query(url)
    metrics = MagicMock()

    handled = await inline_download.handle_inline_download(
        query,
        MagicMock(),
        metrics,
    )

    assert handled is True
    results = query.answer.await_args.args[0]
    assert len(results) == 1
    assert isinstance(results[0], InlineQueryResultCachedPhoto)
    assert results[0].photo_file_id == "photo-file"
    assert query.answer.await_args.kwargs == {
        "cache_time": 3600,
        "is_personal": True,
    }
    metrics.inc.assert_called_once_with(
        "bot_downloads_total",
        {"download_type": "threads.com_inline"},
    )


async def test_yandex_audio_upload_sets_telegram_title(monkeypatch):
    async def download_yandex_audio(_url, directory):
        filepath = Path(directory) / "Название песни.mp3"
        filepath.write_bytes(b"audio")
        return str(filepath)

    message = MagicMock()
    message.audio.file_id = "audio-file"
    bot = MagicMock()
    bot.send_audio = AsyncMock(return_value=message)
    bot.delete_message = AsyncMock()
    monkeypatch.setattr(
        inline_download,
        "download_yandex_audio",
        download_yandex_audio,
    )

    medias = await inline_download._upload_yandex_audio(
        "https://music.yandex.ru/track/1",
        bot,
    )

    assert medias == [CachedMedia(file_id="audio-file", kind="audio")]
    assert bot.send_audio.await_args.kwargs["filename"] == "Название песни.mp3"
    assert bot.send_audio.await_args.kwargs["title"] == "Название песни"


async def test_fast_inline_failure_returns_personal_error(monkeypatch):
    url = "https://www.instagram.com/reel/Failed123/"
    monkeypatch.setattr(
        inline_download,
        "_get_medias",
        AsyncMock(side_effect=ValueError("resolver failed")),
    )
    query = _query(url)

    handled = await inline_download.handle_inline_download(
        query,
        MagicMock(),
        MagicMock(),
    )

    assert handled is True
    result = query.answer.await_args.args[0][0]
    assert isinstance(result, InlineQueryResultArticle)
    assert result.title == "❌ Не получилось скачать"
    assert "resolver failed" in result.description
    assert query.answer.await_args.kwargs == {
        "cache_time": 10,
        "is_personal": True,
    }


async def test_loader_timeout_is_reported_as_failure(monkeypatch):
    url = "https://www.instagram.com/reel/Timeout123/"
    monkeypatch.setattr(
        inline_download,
        "_get_medias",
        AsyncMock(side_effect=TimeoutError("resolver timed out")),
    )
    query = _query(url)

    handled = await inline_download.handle_inline_download(
        query,
        MagicMock(),
        MagicMock(),
    )

    assert handled is True
    result = query.answer.await_args.args[0][0]
    assert result.title == "❌ Не получилось скачать"
    assert "resolver timed out" in result.description
    assert inline_download._pending_ctx == {}


async def test_slow_inline_download_returns_replaceable_loader(monkeypatch):
    url = "https://www.instagram.com/reel/Slow123/"
    release = asyncio.Event()
    media = CachedMedia(
        file_id="video-file",
        caption="Описание",
        kind="video",
    )

    async def get_medias(*_):
        await release.wait()
        return [media]

    monkeypatch.setattr(inline_download, "_get_medias", get_medias)
    monkeypatch.setattr(inline_download, "_INLINE_QUERY_WAIT_SECONDS", 0.01)
    query = _query(url)
    metrics = MagicMock()
    bot = MagicMock()
    bot.edit_message_media = AsyncMock()

    handled = await inline_download.handle_inline_download(
        query,
        bot,
        metrics,
    )

    assert handled is True
    results = query.answer.await_args.args[0]
    assert len(results) == 1
    assert isinstance(results[0], InlineQueryResultArticle)
    assert "Догружаю" in results[0].title
    pending_button = results[0].reply_markup.inline_keyboard[0][0]
    assert pending_button.callback_data == (
        f"{inline_download._PENDING_CALLBACK_PREFIX}{results[0].id}"
    )
    assert results[0].reply_markup.inline_keyboard[1][0].url == url
    assert query.answer.await_args.kwargs == {
        "cache_time": 0,
        "is_personal": True,
    }
    pending = inline_download._pending_ctx[results[0].id]
    assert pending.task.cancelled() is False

    release.set()
    await pending.task
    await asyncio.sleep(0)
    handled = await inline_download.handle_chosen_inline_result(
        _chosen(results[0].id),
        bot,
        MagicMock(),
    )

    assert handled is True
    edited = bot.edit_message_media.await_args.kwargs["media"]
    assert isinstance(edited, InputMediaVideo)
    assert edited.media == "video-file"
    assert edited.caption == "Описание"
    assert (
        bot.edit_message_media.await_args.kwargs["reply_markup"]
        .inline_keyboard[0][0]
        .url
        == url
    )
    assert results[0].id not in inline_download._pending_ctx
    metrics.inc.assert_called_once_with(
        "bot_downloads_total",
        {"download_type": "instagram.com_inline"},
    )


@pytest.mark.parametrize(
    ("kind", "expected_type"),
    [
        ("photo", InputMediaPhoto),
        ("video", InputMediaVideo),
        ("audio", InputMediaAudio),
    ],
)
async def test_pending_result_uses_cached_media_type(kind, expected_type):
    task = asyncio.create_task(asyncio.sleep(
        0,
        result=[CachedMedia(file_id="file-id", kind=kind)],
    ))
    pending = inline_download._PendingCtx(
        url="https://example.com/source",
        task=task,
    )
    bot = MagicMock()
    bot.edit_message_media = AsyncMock()

    await inline_download._finish_pending_result(
        pending,
        "inline-message",
        bot,
    )

    assert isinstance(
        bot.edit_message_media.await_args.kwargs["media"],
        expected_type,
    )


async def test_pending_result_uses_first_carousel_item_and_links_remaining():
    url = "https://www.instagram.com/p/Carousel123/?utm_source=test"
    task = asyncio.create_task(asyncio.sleep(
        0,
        result=[
            CachedMedia(file_id="first", kind="photo"),
            CachedMedia(file_id="second", kind="video"),
        ],
    ))
    pending = inline_download._PendingCtx(
        url=url,
        task=task,
    )
    bot = MagicMock()
    bot.edit_message_media = AsyncMock()

    await inline_download._finish_pending_result(
        pending,
        "inline-message",
        bot,
    )

    media = bot.edit_message_media.await_args.kwargs["media"]
    assert isinstance(media, InputMediaPhoto)
    assert media.media == "first"
    markup = bot.edit_message_media.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].url == url
    remaining_button = markup.inline_keyboard[0][1]
    assert remaining_button.text == "Остальные (1)"
    assert remaining_button.switch_inline_query_current_chat == (
        "https://www.instagram.com/p/Carousel123/"
    )


async def test_pending_channel_carousel_omits_unsupported_switch_button():
    task = asyncio.create_task(asyncio.sleep(
        0,
        result=[
            CachedMedia(file_id="first", kind="photo"),
            CachedMedia(file_id="second", kind="photo"),
        ],
    ))
    pending = inline_download._PendingCtx(
        url="https://www.instagram.com/p/Carousel123/",
        task=task,
        chat_type="channel",
    )
    bot = MagicMock()
    bot.edit_message_media = AsyncMock()

    await inline_download._finish_pending_result(
        pending,
        "inline-message",
        bot,
    )

    markup = bot.edit_message_media.await_args.kwargs["reply_markup"]
    assert len(markup.inline_keyboard[0]) == 1
    assert markup.inline_keyboard[0][0].url == pending.url


async def test_pending_callback_replaces_loader():
    result_id = "pending-result"
    task = asyncio.create_task(asyncio.sleep(
        0,
        result=[CachedMedia(file_id="photo-file", kind="photo")],
    ))
    inline_download._pending_ctx[result_id] = inline_download._PendingCtx(
        url="https://example.com/source",
        task=task,
    )
    callback = _callback(result_id)
    bot = MagicMock()
    bot.edit_message_media = AsyncMock()

    handled = await inline_download.handle_pending_inline_callback(
        callback,
        bot,
    )

    assert handled is True
    callback.answer.assert_awaited_once_with("Догружаю…")
    assert result_id not in inline_download._pending_ctx
    assert bot.edit_message_media.await_args.kwargs["inline_message_id"] == (
        "inline-message"
    )


async def test_pending_callback_ack_failure_still_replaces_loader():
    result_id = "pending-result"
    task = asyncio.create_task(asyncio.sleep(
        0,
        result=[CachedMedia(file_id="photo-file", kind="photo")],
    ))
    inline_download._pending_ctx[result_id] = inline_download._PendingCtx(
        url="https://example.com/source",
        task=task,
    )
    callback = _callback(result_id)
    callback.answer.side_effect = RuntimeError("answer failed")
    bot = MagicMock()
    bot.edit_message_media = AsyncMock()

    handled = await inline_download.handle_pending_inline_callback(
        callback,
        bot,
    )

    assert handled is True
    assert result_id not in inline_download._pending_ctx
    bot.edit_message_media.assert_awaited_once()


async def test_pending_edit_failure_can_be_retried():
    result_id = "pending-result"
    task = asyncio.create_task(asyncio.sleep(
        0,
        result=[CachedMedia(file_id="photo-file", kind="photo")],
    ))
    pending = inline_download._PendingCtx(
        url="https://example.com/source",
        task=task,
    )
    inline_download._pending_ctx[result_id] = pending
    callback = _callback(result_id)
    bot = MagicMock()
    bot.edit_message_media = AsyncMock(side_effect=[
        RuntimeError("edit failed"),
        None,
    ])

    with pytest.raises(RuntimeError, match="edit failed"):
        await inline_download.handle_pending_inline_callback(
            callback,
            bot,
        )

    assert inline_download._pending_ctx[result_id] is pending
    assert pending.delivery_task is None

    handled = await inline_download.handle_pending_inline_callback(
        callback,
        bot,
    )

    assert handled is True
    assert result_id not in inline_download._pending_ctx
    assert bot.edit_message_media.await_count == 2


async def test_cancelled_delivery_continues_in_background():
    result_id = "pending-result"
    release = asyncio.Event()

    async def get_medias():
        await release.wait()
        return [CachedMedia(file_id="photo-file", kind="photo")]

    task = asyncio.create_task(get_medias())
    pending = inline_download._PendingCtx(
        url="https://example.com/source",
        task=task,
    )
    inline_download._pending_ctx[result_id] = pending
    callback = _callback(result_id)
    bot = MagicMock()
    bot.edit_message_media = AsyncMock()
    delivery = asyncio.create_task(
        inline_download.handle_pending_inline_callback(
            callback,
            bot,
        )
    )
    while pending.delivery_task is None:
        await asyncio.sleep(0)

    delivery.cancel()
    with pytest.raises(asyncio.CancelledError):
        await delivery

    assert inline_download._pending_ctx[result_id] is pending
    media_delivery = pending.delivery_task
    assert media_delivery is not None

    release.set()
    await media_delivery
    await asyncio.sleep(0)

    assert result_id not in inline_download._pending_ctx
    bot.edit_message_media.assert_awaited_once()


async def test_chosen_and_callback_share_one_delivery():
    result_id = "pending-result"
    release = asyncio.Event()

    async def get_medias():
        await release.wait()
        return [CachedMedia(file_id="photo-file", kind="photo")]

    pending = inline_download._PendingCtx(
        url="https://example.com/source",
        task=asyncio.create_task(get_medias()),
    )
    inline_download._pending_ctx[result_id] = pending
    bot = MagicMock()
    bot.edit_message_media = AsyncMock()
    chosen_delivery = asyncio.create_task(
        inline_download.handle_chosen_inline_result(
            _chosen(result_id),
            bot,
            MagicMock(),
        )
    )
    callback_delivery = asyncio.create_task(
        inline_download.handle_pending_inline_callback(
            _callback(result_id),
            bot,
        )
    )
    await asyncio.sleep(0)

    release.set()
    assert await chosen_delivery is True
    assert await callback_delivery is True
    assert result_id not in inline_download._pending_ctx
    bot.edit_message_media.assert_awaited_once()


async def test_cancelled_pending_callback_can_be_retried():
    result_id = "pending-result"
    task = asyncio.create_task(asyncio.sleep(0, result=[]))
    inline_download._pending_ctx[result_id] = inline_download._PendingCtx(
        url="https://example.com/source",
        task=task,
    )
    callback = _callback(result_id)
    callback.answer.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await inline_download.handle_pending_inline_callback(
            callback,
            MagicMock(),
        )

    assert inline_download._pending_ctx[result_id].task is task
    await task


async def test_pending_callback_keeps_context_without_inline_message_id():
    result_id = "pending-result"
    task = asyncio.create_task(asyncio.sleep(0, result=[]))
    inline_download._pending_ctx[result_id] = inline_download._PendingCtx(
        url="https://example.com/source",
        task=task,
    )
    callback = _callback(result_id, None)

    handled = await inline_download.handle_pending_inline_callback(
        callback,
        MagicMock(),
    )

    assert handled is True
    assert result_id in inline_download._pending_ctx
    callback.answer.assert_awaited_once_with(
        "Не могу обновить это сообщение",
        show_alert=True,
    )
    await task


async def test_stale_pending_callback_is_acknowledged():
    callback = _callback("missing-result")

    handled = await inline_download.handle_pending_inline_callback(
        callback,
        MagicMock(),
    )

    assert handled is True
    callback.answer.assert_awaited_once_with("Уже обработано")


async def test_unrelated_callback_is_not_handled():
    callback = _callback("unused")
    callback.data = "another-feature"

    handled = await inline_download.handle_pending_inline_callback(
        callback,
        MagicMock(),
    )

    assert handled is False
    callback.answer.assert_not_awaited()


async def test_bot_routes_pending_callback_before_features(monkeypatch):
    handle_pending = AsyncMock(return_value=True)
    monkeypatch.setattr(
        inline_download,
        "handle_pending_inline_callback",
        handle_pending,
    )
    callback = MagicMock()
    update = MagicMock()
    update.callback_query = callback
    bot = Bot.__new__(Bot)
    bot.bot = MagicMock()

    await bot._callback(update, MagicMock())

    handle_pending.assert_awaited_once_with(callback, bot.bot)


async def test_pending_failure_replaces_loader_with_error(monkeypatch):
    url = "https://www.instagram.com/reel/Failed123/"
    release = asyncio.Event()

    async def get_medias(*_):
        await release.wait()
        raise ValueError("resolver failed")

    monkeypatch.setattr(inline_download, "_get_medias", get_medias)
    monkeypatch.setattr(inline_download, "_INLINE_QUERY_WAIT_SECONDS", 0.01)
    query = _query(url)
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    await inline_download.handle_inline_download(
        query,
        bot,
        MagicMock(),
    )
    result = query.answer.await_args.args[0][0]
    release.set()
    await asyncio.sleep(0)

    handled = await inline_download.handle_chosen_inline_result(
        _chosen(result.id),
        bot,
        MagicMock(),
    )

    assert handled is True
    assert "resolver failed" in bot.edit_message_text.await_args.kwargs["text"]


async def test_empty_pending_result_replaces_loader_with_error():
    task = asyncio.create_task(asyncio.sleep(0, result=[]))
    pending = inline_download._PendingCtx(
        url="https://example.com/source",
        task=task,
    )
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    await inline_download._finish_pending_result(
        pending,
        "inline-message",
        bot,
    )

    assert bot.edit_message_text.await_args.kwargs["text"] == (
        "❌ Загрузчик не вернул медиа"
    )


async def test_pending_result_without_inline_message_id_returns_false(monkeypatch):
    url = "https://www.instagram.com/reel/Slow123/"
    release = asyncio.Event()

    async def get_medias(*_):
        await release.wait()
        return [CachedMedia(file_id="file-id")]

    monkeypatch.setattr(inline_download, "_get_medias", get_medias)
    monkeypatch.setattr(inline_download, "_INLINE_QUERY_WAIT_SECONDS", 0.01)
    query = _query(url)

    await inline_download.handle_inline_download(
        query,
        MagicMock(),
        MagicMock(),
    )
    result = query.answer.await_args.args[0][0]

    handled = await inline_download.handle_chosen_inline_result(
        _chosen(result.id, None),
        MagicMock(),
        MagicMock(),
    )

    assert handled is False
    assert result.id in inline_download._pending_ctx
    release.set()
    await asyncio.sleep(0)


async def test_expired_loader_answer_drops_pending_context(monkeypatch):
    url = "https://www.instagram.com/reel/Slow123/"
    release = asyncio.Event()

    async def get_medias(*_):
        await release.wait()
        return [CachedMedia(file_id="file-id")]

    monkeypatch.setattr(inline_download, "_get_medias", get_medias)
    monkeypatch.setattr(inline_download, "_INLINE_QUERY_WAIT_SECONDS", 0.01)
    query = _query(url)
    query.answer.side_effect = BadRequest("Query is too old")

    await inline_download.handle_inline_download(
        query,
        MagicMock(),
        MagicMock(),
    )

    assert inline_download._pending_ctx == {}
    release.set()
    await asyncio.sleep(0)


async def test_cancelled_handler_keeps_download_running(monkeypatch):
    url = "https://www.instagram.com/reel/Slow123/"
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def get_medias(*_):
        started.set()
        await release.wait()
        completed.set()
        return [CachedMedia(file_id="file-id")]

    monkeypatch.setattr(inline_download, "_get_medias", get_medias)
    query = _query(url)
    metrics = MagicMock()
    handler = asyncio.create_task(inline_download.handle_inline_download(
        query,
        MagicMock(),
        metrics,
    ))
    await started.wait()

    handler.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler

    release.set()
    await completed.wait()
    await asyncio.sleep(0)

    metrics.inc.assert_called_once_with(
        "bot_downloads_total",
        {"download_type": "instagram.com_inline"},
    )


async def test_answer_failure_drops_context_and_keeps_download(monkeypatch):
    url = "https://www.instagram.com/reel/Slow123/"
    release = asyncio.Event()
    completed = asyncio.Event()

    async def get_medias(*_):
        await release.wait()
        completed.set()
        return [CachedMedia(file_id="file-id")]

    monkeypatch.setattr(inline_download, "_get_medias", get_medias)
    monkeypatch.setattr(inline_download, "_INLINE_QUERY_WAIT_SECONDS", 0.01)
    query = _query(url)
    query.answer.side_effect = RuntimeError("telegram unavailable")
    metrics = MagicMock()

    with pytest.raises(RuntimeError, match="telegram unavailable"):
        await inline_download.handle_inline_download(
            query,
            MagicMock(),
            metrics,
        )

    assert inline_download._pending_ctx == {}

    release.set()
    await completed.wait()
    await asyncio.sleep(0)

    metrics.inc.assert_called_once_with(
        "bot_downloads_total",
        {"download_type": "instagram.com_inline"},
    )


async def test_tracking_query_variants_share_one_download(monkeypatch):
    release = asyncio.Event()
    started = asyncio.Event()
    calls = 0

    async def load_medias(*_):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return [CachedMedia(file_id="file-id")]

    monkeypatch.setattr(inline_download, "_load_medias", load_medias)
    first = asyncio.create_task(inline_download._get_medias(
        "https://www.instagram.com/reel/Post123/?utm_source=one",
        "instagram.com",
        MagicMock(),
    ))
    second = asyncio.create_task(inline_download._get_medias(
        "https://www.instagram.com/reel/Post123/?utm_source=two",
        "instagram.com",
        MagicMock(),
    ))
    await started.wait()
    await asyncio.sleep(0)

    assert calls == 1

    release.set()
    assert await first == await second
    assert len(video_cache._cache) == 1


def test_media_cache_key_keeps_required_query_parameters():
    youtube = "https://youtube.com/watch?v=video-id"

    assert inline_download._media_cache_key(youtube, "youtube.com") == youtube
    assert inline_download._media_cache_key(
        "https://WWW.INSTAGRAM.COM/reel/Post123/?utm_source=test#fragment",
        "instagram.com",
    ) == "https://www.instagram.com/reel/Post123/"
