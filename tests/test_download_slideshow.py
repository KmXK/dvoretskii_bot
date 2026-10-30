import time
from contextlib import asynccontextmanager
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import InputMediaPhoto, Message
from telegram.error import TimedOut

from steward.bot import inline_download
from steward.features.download import callbacks
from steward.features.download.slideshow import try_send_photo_slideshow
from steward.features.download.video_cache import CachedMedia
from tests.conftest import CHAT_ID, MockRequest, make_bot, make_repository


class SlideshowRequest(MockRequest):
    async def do_request(self, url, method, request_data=None, **kwargs):
        if url.endswith("/sendRichMessage"):
            self.uploads = request_data.multipart_data
        return await super().do_request(url, method, request_data=request_data, **kwargs)


@pytest.mark.parametrize("remote", [False, True])
async def test_photo_download_sends_one_slideshow_with_all_files(monkeypatch, tmp_path, remote):
    paths = []
    for index in range(11):
        path = tmp_path / f"{index}.jpg"
        path.write_bytes(f"photo-{index}".encode())
        paths.append(str(path))

    closed = []

    @asynccontextmanager
    async def download(url, **kwargs):
        with open(url, "rb") as file:
            yield file
        closed.append(url)

    monkeypatch.setattr(callbacks, "download_file", download)
    request = SlideshowRequest()
    bot, app = await make_bot(request)
    message = Message.de_json({
        "message_id": 42, "date": int(time.time()),
        "chat": {"id": CHAT_ID, "type": "supergroup", "title": "Test"},
        "is_topic_message": True, "message_thread_id": 7,
    }, bot)
    caption = '<b>Пост &amp; фото</b>\n<a href="https://example.com">Источник</a>'
    try:
        if remote:
            await callbacks.download_and_send_medias(
                make_repository(), message, [(path, False) for path in paths], caption=caption,
            )
            assert closed == paths
        else:
            await callbacks.send_media_files(message, paths, caption=caption)

        sent = [(endpoint, params) for endpoint, params in request.calls if endpoint.startswith("send")]
        assert len(sent) == 1
        endpoint, params = sent[0]
        assert endpoint == "sendRichMessage"
        assert params["chat_id"] == CHAT_ID
        assert params["message_thread_id"] == 7
        assert params["reply_parameters"] == {"message_id": 42, "allow_sending_without_reply": True}
        rich = params["rich_message"]
        assert rich["html"].count("<img ") == 11
        assert rich["html"].count("Пост &amp; фото") == 1
        assert '<br><a href="https://example.com">Источник</a>' in rich["html"]
        for index, item in enumerate(rich["media"]):
            attachment = item["media"]["media"].removeprefix("attach://")
            assert request.uploads[attachment][1] == f"photo-{index}".encode()
    finally:
        await app.shutdown()


async def test_slideshow_timeout_is_not_retried_as_an_album():
    message = MagicMock()
    message.get_bot.return_value.do_api_request = AsyncMock(side_effect=TimedOut())
    medias = [InputMediaPhoto(BytesIO(b"one")), InputMediaPhoto(BytesIO(b"two"))]
    with pytest.raises(TimedOut):
        await try_send_photo_slideshow(message, medias)
    message.get_bot.return_value.do_api_request.assert_awaited_once()


async def test_inline_carousel_serializes_cached_photos_caption_and_music():
    medias = [
        CachedMedia(file_id="first", kind="photo", caption="<b>Описание</b>"),
        CachedMedia(file_id="second", kind="photo", caption="<b>Описание</b>"),
        CachedMedia(file_id="music", kind="audio"),
    ]
    results = inline_download._to_results(medias, "https://example.com", "tiktok")
    request = MockRequest()
    bot, app = await make_bot(request)
    try:
        await bot.answer_inline_query("query-id", results)
        params = next(params for endpoint, params in request.calls if endpoint == "answerInlineQuery")
        serialized = params["results"]
    finally:
        await app.shutdown()
    rich = serialized[0]["input_message_content"]["rich_message"]
    assert [item["media"]["media"] for item in rich["media"]] == ["first", "second", "music"]
    assert rich["html"].startswith("<tg-slideshow>")
    assert rich["html"].count("Описание") == 1
    assert '<audio src="tg://audio?id=audio_0"></audio>' in rich["html"]
    assert len(serialized) == 4


async def test_pending_carousel_edits_message_with_cached_photos_and_music():
    import asyncio

    medias = [
        CachedMedia(file_id="first", kind="photo"),
        CachedMedia(file_id="second", kind="photo"),
        CachedMedia(file_id="music", kind="audio"),
    ]
    task = asyncio.create_task(asyncio.sleep(0, result=medias))
    pending = inline_download._PendingCtx(url="https://example.com", task=task)
    request = MockRequest()
    bot, app = await make_bot(request)
    try:
        await inline_download._finish_pending_result(pending, "inline-message", bot)
        params = next(params for endpoint, params in request.calls if endpoint == "editMessageText")
        assert params["inline_message_id"] == "inline-message"
        assert len(params["rich_message"]["media"]) == 3
        assert params["reply_markup"]["inline_keyboard"] == [[{"text": "Источник", "url": pending.url}]]
        assert not any(endpoint == "editMessageMedia" for endpoint, _ in request.calls)
    finally:
        await app.shutdown()
