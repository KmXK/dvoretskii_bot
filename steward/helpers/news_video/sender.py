"""Send composed video to Telegram. Lives in helpers/ to keep the raw `reply_video`
call out of steward/features/ (lint rule in tests/test_no_raw_telegram_in_features.py).
"""
from __future__ import annotations

import logging
from pathlib import Path

from telegram import InputFile, Message

logger = logging.getLogger(__name__)


async def send_news_video(message: Message, video_path: Path, caption: str = "") -> None:
    with video_path.open("rb") as f:
        await message.reply_video(
            video=InputFile(f, filename=video_path.name),
            caption=caption or None,
        )


async def send_voice_reply(message: Message, audio_path: Path) -> None:
    with audio_path.open("rb") as f:
        await message.reply_voice(voice=InputFile(f, filename=audio_path.name))
