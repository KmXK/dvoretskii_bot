"""Shared helpers for Telegram file IO, ffmpeg, and ffprobe.

Features that need to download a Telegram attachment, probe a media duration,
or invoke ffmpeg should use these helpers instead of reimplementing them.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from aiohttp_socks import ProxyConnector
from telegram.ext import ExtBot

logger = logging.getLogger(__name__)

_VIDEO_SUFFIXES = frozenset({".mkv", ".mov", ".mp4", ".webm"})
_FILE_DOWNLOAD_CHUNK_SIZE = 64 * 1024
_FILE_DOWNLOAD_TIMEOUT = 30


def is_video_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _VIDEO_SUFFIXES


def _strip_file_url(file_path: str) -> str:
    if not (file_path.startswith("http://") or file_path.startswith("https://")):
        return file_path
    path = urlparse(file_path).path
    if path.startswith("/file/bot"):
        rest = path[len("/file/bot"):]
        slash_idx = rest.find("/")
        if slash_idx > 0:
            return rest[slash_idx + 1:]
    return path.lstrip("/")


async def fetch_tg_file_bytes(bot: ExtBot, file_id: str) -> bytes:
    """Return the raw bytes of a Telegram file.

    Tries the local-mode path `/data/{token}/{file_path}` first (mounted when
    running against the local Bot API server), falls back to downloading via
    `get_file().download_as_bytearray()`.
    """
    tg_file = await bot.get_file(file_id)
    if tg_file.file_path:
        rel = _strip_file_url(tg_file.file_path)
        local_path = Path(f"/data/{bot.token}/{rel}")
        if local_path.exists():
            return local_path.read_bytes()
    return bytes(await tg_file.download_as_bytearray())


async def fetch_tg_file_to(
    bot: ExtBot,
    file_id: str,
    dest: Path,
    *,
    max_bytes: int | None = None,
) -> Path:
    """Download a Telegram file to `dest` on disk. Returns `dest`.

    Uses the local-mode path when available to avoid a round trip.
    """
    tg_file = await bot.get_file(file_id)
    file_path = getattr(tg_file, "file_path", None)
    if not file_path:
        raise RuntimeError("Telegram не вернул путь к файлу")

    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes не может быть отрицательным")

    file_size = getattr(tg_file, "file_size", None)
    if max_bytes is not None and file_size is not None and file_size > max_bytes:
        raise ValueError(
            f"Размер файла Telegram превышает лимит {max_bytes} байт"
        )

    started = False
    try:
        rel = _strip_file_url(file_path)
        local_path = Path(f"/data/{bot.token}/{rel}")
        if local_path.exists():
            with local_path.open("rb") as source, dest.open("wb") as output:
                started = True
                copied = 0
                while True:
                    chunk = source.read(_FILE_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if max_bytes is not None and copied > max_bytes:
                        raise ValueError(
                            f"Размер файла Telegram превышает лимит {max_bytes} байт"
                        )
                    output.write(chunk)
                    await asyncio.sleep(0)
            return dest

        if not file_path.startswith(("http://", "https://")):
            raise RuntimeError("Telegram вернул относительный путь к файлу")

        try:
            proxy_url = os.environ.get("DOWNLOAD_PROXY")
            if proxy_url:
                try:
                    connector = ProxyConnector.from_url(proxy_url)
                except ValueError:
                    raise RuntimeError(
                        "Не удалось настроить прокси для скачивания файла"
                    ) from None
            else:
                connector = None
            timeout = aiohttp.ClientTimeout(total=_FILE_DOWNLOAD_TIMEOUT)
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
            ) as session:
                async with session.get(file_path) as response:
                    if response.status < 200 or response.status >= 300:
                        raise RuntimeError(
                            f"Telegram вернул HTTP {response.status} при скачивании файла"
                        )
                    if (
                        max_bytes is not None
                        and response.content_length is not None
                        and response.content_length > max_bytes
                    ):
                        raise ValueError(
                            f"Размер файла Telegram превышает лимит {max_bytes} байт"
                        )

                    downloaded = 0
                    with dest.open("wb") as output:
                        started = True
                        async for chunk in response.content.iter_chunked(
                            _FILE_DOWNLOAD_CHUNK_SIZE
                        ):
                            downloaded += len(chunk)
                            if max_bytes is not None and downloaded > max_bytes:
                                raise ValueError(
                                    f"Размер файла Telegram превышает лимит {max_bytes} байт"
                                )
                            output.write(chunk)
                            await asyncio.sleep(0)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise RuntimeError("Не удалось скачать файл Telegram") from None
        return dest
    except BaseException:
        if started:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        raise


async def ffprobe_duration(path: Path) -> float:
    """Return media duration in seconds via ffprobe. Raises on failure."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    out = stdout.decode().strip()
    if not out:
        raise RuntimeError(f"ffprobe returned empty duration for {path}")
    return float(out)


async def has_audio_stream(path: Path) -> bool:
    """True if the file contains at least one audio stream.

    Some TikTok formats (notably bytevc1/h265 gear variants) are tagged
    `acodec=aac` by yt-dlp but ship without a real audio track, so the metadata
    can't be trusted — probe the actual file instead.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return bool(stdout.decode().strip())


async def run_ffmpeg(*args: str) -> None:
    """Run `ffmpeg -y <args>`. Raises RuntimeError with stderr on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()}")
