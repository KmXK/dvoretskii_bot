import asyncio
import base64
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

import steward.features.download.callbacks as download_callbacks
from steward.features.download.callbacks import (
    DownloadBudget,
    _media_group_chunks,
    download_and_send_medias,
    download_file,
    enter_download_contexts,
    send_media_files,
)
from steward.features.download.image_description import describe_image_files
from steward.features.download.yt import (
    _gallery_audio_filename,
    _make_caption,
    make_images_loader,
)
from steward.helpers.ai import _yandex_vlm_headers
from tests.conftest import make_repository


def _image(path: Path, color: tuple[int, int, int]) -> Path:
    Image.new("RGB", (120, 80), color).save(path, format="JPEG")
    return path


def test_media_group_chunks_never_leave_single_item_group():
    assert _media_group_chunks(list(range(10))) == [list(range(10))]
    assert _media_group_chunks(list(range(11))) == [
        list(range(9)),
        [9, 10],
    ]
    assert _media_group_chunks(list(range(20))) == [
        list(range(10)),
        list(range(10, 20)),
    ]
    assert _media_group_chunks(list(range(21))) == [
        list(range(10)),
        list(range(10, 19)),
        [19, 20],
    ]


async def test_download_budget_rejects_total_overflow():
    budget = DownloadBudget(5)

    await budget.consume(3)

    with pytest.raises(ValueError, match="общий размер"):
        await budget.consume(3)


async def test_download_contexts_limit_concurrency():
    active = 0
    peak = 0

    class Context:
        async def __aenter__(self):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    contexts = [Context() for _ in range(8)]

    results = await enter_download_contexts(
        contexts,
        max_concurrency=3,
    )

    assert len(results) == 8
    assert peak == 3


async def test_download_file_rejects_stream_larger_than_limit(monkeypatch):
    response = MagicMock()
    response.content_length = None
    response.raise_for_status = MagicMock()
    response.content.readany = AsyncMock(
        side_effect=[
            b"123",
            b"456",
            b"",
        ]
    )
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.get.return_value = response
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)
    monkeypatch.setattr(
        download_callbacks.aiohttp,
        "ClientSession",
        MagicMock(return_value=session),
    )

    with pytest.raises(ValueError, match="размер файла"):
        async with download_file(
            "https://scontent.test.cdninstagram.com/video.mp4",
            max_bytes=5,
        ):
            pass


def test_gallery_audio_filename_uses_track_and_artist():
    metadata = {
        "music": {
            "title": "Night Drive",
            "authorName": "DJ Test",
        }
    }

    assert _gallery_audio_filename(metadata, "2.mp3") == (
        "Night Drive — DJ Test.mp3"
    )


def test_vlm_headers_prefer_vision_secret(monkeypatch):
    monkeypatch.setenv("AI_KEY_SECRET", "general-key")
    monkeypatch.setenv("AI_VISION_SECRET", "vision-key")

    assert _yandex_vlm_headers()["Authorization"] == "Api-Key vision-key"


def test_vlm_headers_fall_back_to_general_key(monkeypatch):
    monkeypatch.setenv("AI_KEY_SECRET", "general-key")
    monkeypatch.delenv("AI_VISION_SECRET", raising=False)

    assert _yandex_vlm_headers()["Authorization"] == "Api-Key general-key"


def test_gallery_audio_filename_is_safe_and_keeps_extension():
    metadata = {"music": {"title": 'Bad / Name: *? "track"'}}

    assert _gallery_audio_filename(metadata, "2.m4a") == (
        "Bad Name track.m4a"
    )
    assert _gallery_audio_filename({}, "2.ogg") == "Audio.ogg"


def test_make_caption_uses_gallery_caption_and_limit():
    caption = _make_caption({"caption": "Описание поста"}, limit=10)

    assert "Описание" in caption
    assert "Описание…" in caption


async def test_multiple_images_are_sent_to_vlm_as_one_collage(monkeypatch, tmp_path):
    paths = [
        _image(tmp_path / "1.jpg", (255, 0, 0)),
        _image(tmp_path / "2.jpg", (0, 255, 0)),
        _image(tmp_path / "3.jpg", (0, 0, 255)),
    ]
    describe = AsyncMock(return_value="  Короткое описание карусели.  ")
    monkeypatch.setenv("AI_KEY_SECRET", "test")
    monkeypatch.setenv("AI_MODEL_VLM", "test-model")
    monkeypatch.setattr(
        "steward.features.download.image_description.make_yandex_vlm_describe",
        describe,
    )

    result = await describe_image_files(paths)

    assert result == "Короткое описание карусели."
    prompt = describe.await_args.args[1]
    images_b64 = describe.await_args.args[2]
    assert "коллаж из 3 картинок" in prompt
    assert len(images_b64) == 1
    collage = Image.open(BytesIO(base64.b64decode(images_b64[0])))
    assert collage.width > 120
    assert collage.height > 80


async def test_send_single_photo_with_post_and_vlm_caption(monkeypatch, tmp_path):
    image_path = _image(tmp_path / "1.jpg", (255, 0, 0))
    message = MagicMock()
    message.reply_photo = AsyncMock()
    describe = AsyncMock(return_value="Красный кадр")
    monkeypatch.setattr(
        "steward.features.download.callbacks.describe_image_files",
        describe,
    )

    await send_media_files(
        message,
        [str(image_path)],
        caption="<i>Описание поста</i>",
        describe_images=True,
    )

    message.reply_photo.assert_awaited_once()
    assert "Красный кадр" in message.reply_photo.await_args.kwargs["caption"]
    assert "Описание поста" in message.reply_photo.await_args.kwargs["caption"]
    assert message.reply_photo.await_args.kwargs["parse_mode"] == "HTML"


async def test_send_media_files_splits_eleven_items_into_valid_groups(
    monkeypatch,
    tmp_path,
):
    image_path = _image(tmp_path / "1.jpg", (255, 0, 0))
    sleep = AsyncMock()
    monkeypatch.setattr("steward.features.download.callbacks.asyncio.sleep", sleep)
    message = MagicMock()
    message.reply_media_group = AsyncMock()

    await send_media_files(
        message,
        [str(image_path)] * 11,
        caption="Описание",
    )

    groups = [call.args[0] for call in message.reply_media_group.await_args_list]
    assert [len(group) for group in groups] == [9, 2]
    sent_medias = [media for group in groups for media in group]
    assert sent_medias[0].caption == "Описание"
    assert all(media.caption is None for media in sent_medias[1:])
    sleep.assert_awaited_once_with(2)


async def test_image_loader_uses_metadata_for_caption_and_audio_name(
    monkeypatch,
    tmp_path,
):
    image_path = _image(tmp_path / "1.jpg", (255, 0, 0))
    audio_path = tmp_path / "2.mp3"
    audio_path.write_bytes(b"audio")
    metadata = {
        "description": "Текст поста",
        "music": {
            "title": "Song",
            "authorName": "Artist",
        },
    }
    send = AsyncMock()
    monkeypatch.setattr(
        "steward.features.download.yt.download_image_files",
        AsyncMock(
            return_value=(
                [str(image_path)],
                [str(audio_path)],
                metadata,
            )
        ),
    )
    monkeypatch.setattr("steward.features.download.yt.send_media_files", send)
    message = MagicMock()
    message.reply_audio = AsyncMock()

    await make_images_loader("tiktok")(
        make_repository(),
        "https://tiktok.example/post",
        message,
    )

    assert "Текст поста" in send.await_args.kwargs["caption"]
    assert send.await_args.kwargs["describe_images"] is True
    message.reply_audio.assert_awaited_once()
    assert message.reply_audio.await_args.kwargs["filename"] == (
        "Song — Artist.mp3"
    )


async def test_remote_media_sender_forwards_headers_and_closes_files(
    monkeypatch,
    tmp_path,
):
    image_path = _image(tmp_path / "1.jpg", (255, 0, 0))
    calls = []
    closed = []

    @asynccontextmanager
    async def download(url, use_proxy=False, request_headers=None, budget=None):
        calls.append((url, use_proxy, request_headers))
        with open(image_path, "rb") as file:
            yield file
        closed.append(url)

    monkeypatch.setattr(
        "steward.features.download.callbacks.download_file",
        download,
    )
    message = MagicMock()
    message.reply_photo = AsyncMock()
    headers = {
        "Referer": "https://www.threads.com/",
        "User-Agent": "crawler",
    }

    await download_and_send_medias(
        MagicMock(),
        message,
        [("https://cdn.example/image.jpg", False)],
        use_proxy=True,
        request_headers=headers,
    )

    assert calls == [("https://cdn.example/image.jpg", True, headers)]
    assert closed == ["https://cdn.example/image.jpg"]
    message.reply_photo.assert_awaited_once()


async def test_remote_video_can_disable_transcription_button(
    monkeypatch,
    tmp_path,
):
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")

    @asynccontextmanager
    async def download(url, use_proxy=False, request_headers=None, budget=None):
        with open(video_path, "rb") as file:
            yield file

    monkeypatch.setattr(
        "steward.features.download.callbacks.download_file",
        download,
    )
    repository = MagicMock()
    repository.save = AsyncMock()
    message = MagicMock()
    message.reply_video = AsyncMock()

    await download_and_send_medias(
        repository,
        message,
        [("https://scontent.test.cdninstagram.com/video.mp4", True)],
        transcription_enabled=False,
    )

    repository.db.saved_links.add.assert_not_called()
    repository.save.assert_not_awaited()
    assert message.reply_video.await_args.kwargs["reply_markup"] is None


async def test_remote_media_sender_splits_eleven_items_into_valid_groups(
    monkeypatch,
    tmp_path,
):
    image_path = _image(tmp_path / "1.jpg", (255, 0, 0))
    closed = []

    @asynccontextmanager
    async def download(url, use_proxy=False, request_headers=None, budget=None):
        with open(image_path, "rb") as file:
            yield file
        closed.append(url)

    monkeypatch.setattr(
        "steward.features.download.callbacks.download_file",
        download,
    )
    sleep = AsyncMock()
    monkeypatch.setattr("steward.features.download.callbacks.asyncio.sleep", sleep)
    message = MagicMock()
    message.reply_media_group = AsyncMock()
    medias = [
        (f"https://cdn.example/{index}.jpg", False)
        for index in range(11)
    ]

    await download_and_send_medias(
        MagicMock(),
        message,
        medias,
        caption="Описание",
    )

    groups = [call.args[0] for call in message.reply_media_group.await_args_list]
    assert [len(group) for group in groups] == [9, 2]
    sent_medias = [media for group in groups for media in group]
    assert sent_medias[0].caption == "Описание"
    assert all(media.caption is None for media in sent_medias[1:])
    assert len(closed) == 11
    sleep.assert_awaited_once_with(2)
