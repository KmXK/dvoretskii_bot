import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest

from steward.features.download import DownloadFeature
from steward.helpers.media import ffprobe_duration, has_audio_stream, run_ffmpeg
from steward.helpers.video_trim import (
    create_trimmed_video_reply,
    fetch_video_to,
    parse_trim_range,
    trim_video,
)
from tests.conftest import make_repository, make_text_context


@pytest.fixture(autouse=True)
def disable_download_rate_limit(monkeypatch):
    monkeypatch.setattr("steward.features.download.check_limit", MagicMock())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0-5", (0.0, 5.0)),
        ("1.25-5.8", (1.25, 5.8)),
        ("1-5.001", (1.0, 5.001)),
        ("1.025-5", (1.025, 5.0)),
        ("1.25 5.8", (1.25, 5.8)),
        ("  1.25 - 5.8  ", (1.25, 5.8)),
        ("1.25\t 5.8", (1.25, 5.8)),
    ],
)
def test_parse_trim_range(text, expected):
    assert parse_trim_range(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "1", "1.25", "-1-5", "1--5", "1,25-5,8", "1:25-5:8", "1-5 extra", "1-5-9"],
)
def test_unrelated_text_is_not_a_trim_range(text):
    assert parse_trim_range(text) is None


def _trim_context(text: str):
    ctx = make_text_context(text)
    ctx.bot.id = 99
    reply = MagicMock()
    reply.from_user.id = 99
    reply.via_bot = None
    reply.video.file_id = "source-video"
    ctx.message.reply_to_message = reply
    return ctx


async def test_reply_range_is_dispatched_to_video_trim(monkeypatch):
    create_reply = AsyncMock()
    monkeypatch.setattr("steward.features.download.create_trimmed_video_reply", create_reply)
    ctx = _trim_context("1.25 5.8")
    feature = DownloadFeature()
    feature.repository = ctx.repository

    assert await feature.chat(ctx) is True
    create_reply.assert_awaited_once_with(
        ctx.bot,
        ctx.client,
        ctx.message,
        ctx.message.reply_to_message,
        1.25,
        5.8,
    )


async def test_inline_video_from_this_bot_can_be_trimmed(monkeypatch):
    create_reply = AsyncMock()
    monkeypatch.setattr("steward.features.download.create_trimmed_video_reply", create_reply)
    ctx = _trim_context("1-5")
    ctx.message.reply_to_message.from_user.id = 77
    ctx.message.reply_to_message.via_bot = MagicMock(id=99)

    assert await DownloadFeature().chat(ctx) is True
    create_reply.assert_awaited_once()


@pytest.mark.parametrize("case", ["no_reply", "no_video", "other_sender", "no_sender", "plain_text"])
async def test_unrelated_messages_are_not_trimmed(monkeypatch, case):
    create_reply = AsyncMock()
    monkeypatch.setattr("steward.features.download.create_trimmed_video_reply", create_reply)
    ctx = _trim_context("1-5")
    feature = DownloadFeature()
    feature.repository = make_repository()

    if case == "no_reply":
        ctx.message.reply_to_message = None
    elif case == "no_video":
        ctx.message.reply_to_message.video = None
    elif case == "other_sender":
        ctx.message.reply_to_message.from_user.id = 77
    elif case == "no_sender":
        ctx.message.reply_to_message.from_user = None
    else:
        ctx.message.text = "хорошее видео"

    assert await feature.chat(ctx) is False
    create_reply.assert_not_awaited()


@pytest.mark.parametrize("text", ["5-1", "5-5", "9" * 400 + "-5"])
async def test_invalid_interval_gets_an_error_before_download(monkeypatch, text):
    fetch = AsyncMock()
    monkeypatch.setattr("steward.helpers.video_trim.fetch_tg_file_to", fetch)
    ctx = _trim_context(text)

    assert await DownloadFeature().chat(ctx) is True
    fetch.assert_not_awaited()
    assert "Конец фрагмента" in ctx.message.reply_text.call_args.kwargs["text"]


async def test_trim_failure_gets_an_error_reply(monkeypatch):
    create_reply = AsyncMock(side_effect=RuntimeError("failed"))
    monkeypatch.setattr("steward.features.download.create_trimmed_video_reply", create_reply)
    ctx = _trim_context("1-5")

    assert await DownloadFeature().chat(ctx) is True
    assert "Не удалось обрезать видео" in ctx.message.reply_text.call_args.kwargs["text"]


@pytest.mark.parametrize("fail_send", [False, True])
async def test_trim_files_are_removed_after_sending(monkeypatch, fail_send):
    paths = []

    async def fetch(bot, client, source_message, destination):
        paths.append(destination)
        destination.write_bytes(b"source")

    async def render(source, output, start, end):
        paths.append(output)
        output.write_bytes(b"trimmed")

    async def send(video, **kwargs):
        assert video.read() == b"trimmed"
        assert kwargs["supports_streaming"] is True
        if fail_send:
            raise RuntimeError("send failed")

    monkeypatch.setattr("steward.helpers.video_trim.fetch_video_to", fetch)
    monkeypatch.setattr("steward.helpers.video_trim.trim_video", render)
    message = MagicMock()
    message.reply_video = AsyncMock(side_effect=send)

    if fail_send:
        with pytest.raises(RuntimeError, match="send failed"):
            await create_trimmed_video_reply(MagicMock(), MagicMock(), message, MagicMock(), 1, 5)
    else:
        await create_trimmed_video_reply(MagicMock(), MagicMock(), message, MagicMock(), 1, 5)

    assert len(paths) == 2
    assert all(not path.exists() and not path.parent.exists() for path in paths)


def _source_message():
    message = MagicMock()
    message.video.file_id = "source-video"
    message.video.file_size = 25 * 1024 * 1024
    message.chat_id = -100123456789
    message.message_id = 42
    return message


async def test_regular_video_uses_bot_api(monkeypatch, tmp_path):
    fetch = AsyncMock()
    monkeypatch.setattr("steward.helpers.video_trim.fetch_tg_file_to", fetch)
    bot = MagicMock()
    client = MagicMock()
    message = _source_message()
    destination = tmp_path / "source.mp4"

    await fetch_video_to(bot, client, message, destination)

    fetch.assert_awaited_once_with(bot, "source-video", destination, max_bytes=50 * 1024 * 1024)
    client.get_messages.assert_not_called()


async def test_large_video_uses_telethon_fallback(monkeypatch, tmp_path):
    fetch = AsyncMock(side_effect=BadRequest("File is too big"))
    monkeypatch.setattr("steward.helpers.video_trim.fetch_tg_file_to", fetch)
    message = _source_message()
    destination = tmp_path / "source.mp4"

    async def download(file):
        Path(file).write_bytes(b"large video")

    source = MagicMock()
    source.download_media = AsyncMock(side_effect=download)
    client = MagicMock()
    client.is_connected.return_value = True
    client.get_messages = AsyncMock(return_value=source)

    await fetch_video_to(MagicMock(), client, message, destination)

    client.get_messages.assert_awaited_once_with(message.chat_id, ids=42)
    source.download_media.assert_awaited_once_with(file=str(destination))
    assert destination.read_bytes() == b"large video"


async def test_unavailable_telethon_has_a_clear_error(monkeypatch, tmp_path):
    fetch = AsyncMock(side_effect=BadRequest("File is too big"))
    monkeypatch.setattr("steward.helpers.video_trim.fetch_tg_file_to", fetch)
    client = MagicMock()
    client.is_connected.return_value = False

    with pytest.raises(ValueError, match="больших видео временно недоступно"):
        await fetch_video_to(MagicMock(), client, _source_message(), tmp_path / "source.mp4")

    client.get_messages.assert_not_called()


async def test_other_bot_api_errors_do_not_use_telethon(monkeypatch, tmp_path):
    fetch = AsyncMock(side_effect=BadRequest("File not found"))
    monkeypatch.setattr("steward.helpers.video_trim.fetch_tg_file_to", fetch)
    client = MagicMock()

    with pytest.raises(BadRequest, match="File not found"):
        await fetch_video_to(MagicMock(), client, _source_message(), tmp_path / "source.mp4")

    client.get_messages.assert_not_called()


async def test_oversized_video_is_rejected_before_download(monkeypatch, tmp_path):
    fetch = AsyncMock()
    monkeypatch.setattr("steward.helpers.video_trim.fetch_tg_file_to", fetch)
    message = _source_message()
    message.video.file_size = 51 * 1024 * 1024

    with pytest.raises(ValueError, match="до 50 МБ"):
        await fetch_video_to(MagicMock(), MagicMock(), message, tmp_path / "source.mp4")

    fetch.assert_not_awaited()


async def _make_test_video(path: Path, with_audio: bool):
    args = [
        "-f", "lavfi",
        "-i", "color=c=red:s=96x64:r=20:d=1",
        "-f", "lavfi",
        "-i", "color=c=blue:s=96x64:r=20:d=2",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=1000:duration=3"]

    args += [
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]",
    ]
    if with_audio:
        args += ["-map", "2:a", "-c:a", "aac"]

    args += [
        "-c:v", "libx264",
        "-g", "100",
        "-sc_threshold", "0",
        "-threads", "2",
        "-filter_complex_threads", "2",
        str(path),
    ]
    await run_ffmpeg(*args)


@pytest.mark.parametrize("with_audio", [False, True])
async def test_trim_video_seeks_between_keyframes_and_preserves_audio(tmp_path, with_audio):
    source = tmp_path / "source.mp4"
    output = tmp_path / "clip.mp4"
    await _make_test_video(source, with_audio)

    await trim_video(source, output, 1.25, 2.1)

    assert await ffprobe_duration(output) == pytest.approx(0.85, abs=0.08)
    assert await has_audio_stream(output) is with_audio

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-v", "error",
        "-threads", "2",
        "-i", str(output),
        "-frames:v", "1",
        "-vf", "scale=1:1",
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    frame, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    red, green, blue = frame
    assert blue > 200 and red < 30 and green < 30


async def test_trim_video_clamps_end_to_video_duration(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "clip.mp4"
    await _make_test_video(source, False)

    await trim_video(source, output, 2, 100)

    assert await ffprobe_duration(output) == pytest.approx(1, abs=0.08)


async def test_trim_video_rejects_start_after_video_end(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "clip.mp4"
    await _make_test_video(source, False)

    with pytest.raises(ValueError, match="Начало фрагмента"):
        await trim_video(source, output, 3, 5)

    assert not output.exists()
