import base64
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from PIL import Image

from steward.features.download.callbacks import send_media_files
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
