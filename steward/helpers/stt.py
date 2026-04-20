import asyncio
import logging
import os
from typing import cast

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_NVIDIA_STT_MODEL = "nvidia/parakeet-ctc-1.1b"


def nvidia_stt_configured() -> bool:
    return bool(os.environ.get("NVIDIA_API_KEY")) and bool(os.environ.get("NVIDIA_STT_URL"))


async def try_nvidia_transcribe_bytes(
    audio: bytes,
    filename: str = "voice.mp3",
    language: str | None = "ru",
) -> str | None:
    api_key = os.environ.get("NVIDIA_API_KEY")
    url = os.environ.get("NVIDIA_STT_URL")
    if not api_key or not url:
        return None

    model = os.environ.get("NVIDIA_STT_MODEL") or _DEFAULT_NVIDIA_STT_MODEL
    files = {"file": (filename, audio, "audio/mpeg")}
    data: dict[str, str] = {"model": model}
    if language:
        data["language"] = language
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=240.0, trust_env=False) as client:
            r = await client.post(url, headers=headers, data=data, files=files)
            if r.status_code >= 400:
                logger.warning("NVIDIA STT HTTP %s: %s", r.status_code, r.text[:300])
                return None
            payload = r.json()
    except Exception as e:
        logger.warning("NVIDIA STT failed: %s", e)
        return None

    text = payload.get("text") if isinstance(payload, dict) else None
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


async def _elevenlabs_transcribe(audio: bytes):
    stt_key = os.environ.get("EVELEN_LABS_STT")
    if not stt_key:
        return None

    try:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(
            api_key=stt_key,
            httpx_client=httpx.Client(
                timeout=240,
                proxy=os.environ.get("DOWNLOAD_PROXY"),
            ),
        )
        try:
            return await asyncio.to_thread(
                lambda: client.speech_to_text.convert(
                    file=audio,
                    model_id="scribe_v1",
                    tag_audio_events=True,
                    diarize=True,
                )
            )
        except Exception as e:
            if "not found" not in str(e).lower():
                raise
            return await asyncio.to_thread(
                lambda: client.speech_to_text.convert(
                    file=audio,
                    tag_audio_events=True,
                    diarize=True,
                )
            )
    except Exception as e:
        logger.exception("ElevenLabs STT failed: %s", e)
        return None


def _strip_speaker_prefixes(named_text: str) -> str:
    lines: list[str] = []
    for line in named_text.splitlines():
        if ":" in line:
            lines.append(line.split(":", 1)[1].strip())
        else:
            lines.append(line.strip())
    return "\n".join(x for x in lines if x).strip()


async def transcribe_audio_bytes(
    audio: bytes,
    *,
    with_speaker_labels: bool = False,
    primary_speaker_name: str | None = None,
) -> str | None:
    nv = await try_nvidia_transcribe_bytes(audio)
    if nv:
        return nv

    result = await _elevenlabs_transcribe(audio)
    if result is None:
        return None

    from elevenlabs.types import SpeechToTextChunkResponseModel
    from steward.helpers.transcription import build_named_speakers_text

    words = cast(SpeechToTextChunkResponseModel, result).words or []
    plain = (getattr(result, "text", "") or "").strip()

    if with_speaker_labels and words:
        named = build_named_speakers_text(words, primary_speaker_name=primary_speaker_name)
        if named:
            return named
    if plain:
        return plain
    if not with_speaker_labels and words:
        named = build_named_speakers_text(words)
        if named:
            cleaned = _strip_speaker_prefixes(named)
            if cleaned:
                return cleaned
    return None
