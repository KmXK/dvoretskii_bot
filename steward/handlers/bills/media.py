"""OCR and voice transcription for /bills."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


async def _read_voice_bytes(context, file_id: str) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    try:
        return bytes(await tg_file.download_as_bytearray())
    except Exception:
        file_path = tg_file.file_path
        if not file_path:
            raise
        if file_path.startswith(("http://", "https://")):
            parsed = urlparse(file_path)
            path = parsed.path
            if path.startswith("/file/bot"):
                rel = path[len("/file/bot"):]
                first_slash = rel.find("/")
                file_path = rel[first_slash + 1:] if first_slash > 0 else rel.lstrip("/")
            else:
                file_path = path.lstrip("/")
        local = Path(f"/data/{context.bot.token}/{file_path}")
        if not local.exists():
            raise
        return local.read_bytes()


async def _transcribe_elevenlabs(data: bytes) -> str | None:
    stt_key = os.environ.get("EVELEN_LABS_STT")
    if not stt_key:
        return None
    with tempfile.TemporaryDirectory(prefix="bills_stt_") as tmp_dir:
        tmp = Path(tmp_dir)
        src, out = tmp / "voice.ogg", tmp / "voice.mp3"
        src.write_bytes(data)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "44100", str(out),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        from elevenlabs.client import ElevenLabs
        import httpx
        client = ElevenLabs(
            api_key=stt_key,
            httpx_client=httpx.Client(timeout=240, proxy=os.environ.get("DOWNLOAD_PROXY")),
        )
        try:
            result = await asyncio.to_thread(lambda: client.speech_to_text.convert(
                file=out.read_bytes(), model_id="scribe_v1", tag_audio_events=True, diarize=True,
            ))
        except Exception as e:
            logger.warning("ElevenLabs STT failed: %s", e)
            return None
    return (getattr(result, "text", None) or "").strip() or None


async def _transcribe_yandex(data: bytes) -> str | None:
    import httpx
    api_key = os.environ.get("SPEECHKIT_API_SECRET") or os.environ.get("AI_VISION_SECRET")
    folder_id = os.environ.get("YC_FOLDER_ID")
    if not api_key or not folder_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize",
                params={"folderId": folder_id, "lang": "ru-RU", "topic": "general", "format": "oggopus"},
                headers={"Authorization": f"Api-Key {api_key}"},
                content=data,
            )
            if resp.status_code != 200:
                logger.warning("Yandex STT %d: %s", resp.status_code, resp.text[:300])
                return None
            return (resp.json().get("result") or "").strip() or None
    except Exception as e:
        logger.warning("Yandex STT failed: %s", e)
        return None


async def transcribe_voice(context, voice) -> str | None:
    data = await _read_voice_bytes(context, voice.file_id)
    return await _transcribe_elevenlabs(data) or await _transcribe_yandex(data)


async def ocr_photo(context, photo) -> str | None:
    api_key = os.environ.get("AI_VISION_SECRET")
    folder_id = os.environ.get("YC_FOLDER_ID")
    if not api_key or not folder_id:
        return None
    from steward.handlers.newtext_handler import _read_photo_bytes, _yandex_ocr
    data = await _read_photo_bytes(context, photo.file_id)
    content_b64 = base64.standard_b64encode(data).decode("ascii")
    mime = "PNG" if data[:8] == b"\x89PNG\r\n\x1a\n" else "JPEG"
    return await _yandex_ocr(content_b64, mime, api_key, folder_id)
