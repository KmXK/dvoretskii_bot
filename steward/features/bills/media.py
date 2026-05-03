"""OCR and voice transcription for /bills, routed through new shared helpers."""
from __future__ import annotations

import base64
import logging

from steward.helpers.media import fetch_tg_file_bytes
from steward.helpers.ocr import extract_text_from_image
from steward.helpers.stt import transcribe_audio_bytes

logger = logging.getLogger(__name__)


async def ocr_photo(bot, photo) -> str | None:
    try:
        data = await fetch_tg_file_bytes(bot, photo.file_id)
    except Exception as e:
        logger.warning("Failed to fetch photo bytes: %s", e)
        return None
    content_b64 = base64.standard_b64encode(data).decode("ascii")
    mime = "PNG" if data[:8] == b"\x89PNG\r\n\x1a\n" else "JPEG"
    text = await extract_text_from_image(content_b64, mime)
    return text or None


async def transcribe_voice(bot, voice) -> str | None:
    try:
        data = await fetch_tg_file_bytes(bot, voice.file_id)
    except Exception as e:
        logger.warning("Failed to fetch voice bytes: %s", e)
        return None
    return await transcribe_audio_bytes(data)
