"""Shared helpers for Telegram file IO, ffmpeg, and ffprobe.

Features that need to download a Telegram attachment, probe a media duration,
or invoke ffmpeg should use these helpers instead of reimplementing them.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

from telegram.ext import ExtBot

logger = logging.getLogger(__name__)


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


async def fetch_tg_file_to(bot: ExtBot, file_id: str, dest: Path) -> Path:
    """Download a Telegram file to `dest` on disk. Returns `dest`.

    Uses the local-mode path when available to avoid a round trip.
    """
    tg_file = await bot.get_file(file_id)
    if tg_file.file_path:
        rel = _strip_file_url(tg_file.file_path)
        local_path = Path(f"/data/{bot.token}/{rel}")
        if local_path.exists():
            dest.write_bytes(local_path.read_bytes())
            return dest
    data = await tg_file.download_as_bytearray()
    dest.write_bytes(bytes(data))
    return dest


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
