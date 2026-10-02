import asyncio
import math
import re
import tempfile
from pathlib import Path

from telegram import Message
from telegram.error import BadRequest
from telegram.ext import ExtBot
from telethon import TelegramClient

from steward.helpers.media import fetch_tg_file_to, ffprobe_duration, run_ffmpeg

_TIME_RANGE = re.compile(r"([0-9]+(?:\.[0-9]+)?)(?:\s*-\s*|\s+)([0-9]+(?:\.[0-9]+)?)")
_TRIM_SLOTS = asyncio.Semaphore(2)
_VIDEO_MAX_BYTES = 50 * 1024 * 1024


def parse_trim_range(text: str) -> tuple[float, float] | None:
    match = _TIME_RANGE.fullmatch(text.strip())
    if match is None:
        return None

    return float(match[1]), float(match[2])


def validate_trim_range(start: float, end: float) -> None:
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("Конец фрагмента должен быть больше начала. Например: 1.25-5.8")


async def trim_video(source: Path, output: Path, start: float, end: float) -> None:
    validate_trim_range(start, end)

    duration = await ffprobe_duration(source)
    if start >= duration:
        raise ValueError(f"Начало фрагмента должно быть меньше длины видео ({duration:g} с).")

    await run_ffmpeg(
        "-ss",
        str(start),
        "-threads",
        "2",
        "-i",
        str(source),
        "-t",
        str(min(end, duration) - start),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-threads",
        "2",
        "-filter_threads",
        "2",
        "-movflags",
        "+faststart",
        str(output),
    )


async def create_trimmed_video_reply(
    bot: ExtBot,
    client: TelegramClient,
    message: Message,
    source_message: Message,
    start: float,
    end: float,
) -> None:
    validate_trim_range(start, end)

    async with _TRIM_SLOTS:
        with tempfile.TemporaryDirectory(prefix="video_trim_") as directory:
            source = Path(directory) / "source.mp4"
            output = Path(directory) / "clip.mp4"
            await fetch_video_to(bot, client, source_message, source)
            await trim_video(source, output, start, end)

            with output.open("rb") as video:
                await message.reply_video(
                    video,
                    filename="clip.mp4",
                    supports_streaming=True,
                )


async def fetch_video_to(
    bot: ExtBot,
    client: TelegramClient,
    message: Message,
    destination: Path,
) -> None:
    video = message.video
    if video is None:
        raise ValueError("В сообщении нет видео.")

    if video.file_size is not None and video.file_size > _VIDEO_MAX_BYTES:
        raise ValueError("Для обрезки подходит видео размером до 50 МБ.")

    try:
        await fetch_tg_file_to(bot, video.file_id, destination, max_bytes=_VIDEO_MAX_BYTES)
        return
    except BadRequest as error:
        if "file is too big" not in str(error).lower():
            raise

    if not client.is_connected():
        raise ValueError("Скачивание больших видео временно недоступно. Попробуй позже.")

    async with asyncio.timeout(120):
        source = await client.get_messages(message.chat_id, ids=message.message_id)
        if source is None or source.video is None:
            raise ValueError("Не удалось найти исходное видео для обрезки.")

        await source.download_media(file=str(destination))

    if not destination.is_file():
        raise RuntimeError("Не удалось скачать видео для обрезки")

    if destination.stat().st_size > _VIDEO_MAX_BYTES:
        raise ValueError("Для обрезки подходит видео размером до 50 МБ.")
