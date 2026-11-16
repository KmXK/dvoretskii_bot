from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from steward.features.download import callbacks, yt
from steward.helpers.video_trim import range_from_link_message
from tests.conftest import make_repository


def test_link_range_uses_same_parser_as_reply():
    message = MagicMock(text="https://vt.tiktok.com/test\n1:20-2:50")
    assert range_from_link_message(message, "https://vt.tiktok.com/test") == (80, 170)
    message.text = "https://vt.tiktok.com/test 5-1"
    with pytest.raises(ValueError):
        range_from_link_message(message, "https://vt.tiktok.com/test")
    message.text = "https://vt.tiktok.com/test 1:60-2:00"
    with pytest.raises(ValueError, match="диапазон"):
        range_from_link_message(message, "https://vt.tiktok.com/test")


async def test_tiktok_link_sends_only_trimmed_video(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"full video")
    url = "https://vt.tiktok.com/test"
    message = MagicMock(text=f"{url}\n1-5")
    message.reply_video = AsyncMock(return_value=None)
    monkeypatch.setattr(yt, "download_video_file", AsyncMock(return_value=({"duration": 20}, str(source))))
    cache = MagicMock()
    monkeypatch.setattr(yt.video_cache, "put", cache)

    async def trim(source_path, output, start, end):
        assert source_path.read_bytes() == b"full video"
        assert (start, end) == (1, 5)
        output.write_bytes(b"clip")

    async def send(video, **kwargs):
        assert video.input_file_content == b"clip"
        return None

    monkeypatch.setattr(yt, "trim_video", trim)
    message.reply_video.side_effect = send
    await yt.make_video_loader("tiktok")(make_repository(), url, message)
    message.reply_video.assert_awaited_once()
    cache.assert_not_called()


async def test_remote_mixed_post_only_sends_clipped_videos(monkeypatch, tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"full video")
    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")

    @asynccontextmanager
    async def download(url, **kwargs):
        with (image if url == "image" else source).open("rb") as file:
            yield file

    async def trim(source_path, output, start, end):
        assert source_path.read_bytes() == b"full video"
        assert (start, end) == (1, 5)
        output.write_bytes(b"clip")

    async def send(message, paths, **kwargs):
        assert len(paths) == 1
        assert Path(paths[0]).read_bytes() == b"clip"

    monkeypatch.setattr(callbacks, "download_file", download)
    monkeypatch.setattr(callbacks, "trim_video", trim)
    send_mock = AsyncMock(side_effect=send)
    monkeypatch.setattr(callbacks, "send_media_files", send_mock)
    await callbacks.download_and_send_medias(
        make_repository(), MagicMock(), [("image", False), ("video", True)], time_range=(1, 5)
    )
    send_mock.assert_awaited_once()
