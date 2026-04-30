import asyncio
import base64
import logging
import os
import time
from typing import cast

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_NVIDIA_STT_MODEL = "nvidia/parakeet-ctc-1.1b"

_ELEVEN_FAIL_THRESHOLD = 3
_ELEVEN_OPEN_DURATION_SEC = 12 * 60 * 60

_ELEVEN_QUOTA_PATTERNS = (
    "quota",
    "insufficient",
    "credit",
    "billing",
    "balance",
    "payment",
    "subscription",
    "exceeded",
    "401",
    "402",
)

_eleven_consecutive_errors = 0
_eleven_open_until = 0.0


def _eleven_circuit_closed() -> bool:
    return time.time() >= _eleven_open_until


def _eleven_open_circuit(reason: str) -> None:
    global _eleven_consecutive_errors, _eleven_open_until
    _eleven_open_until = time.time() + _ELEVEN_OPEN_DURATION_SEC
    _eleven_consecutive_errors = 0
    logger.warning(
        "ElevenLabs STT circuit opened for %d hours (%s)",
        _ELEVEN_OPEN_DURATION_SEC // 3600,
        reason,
    )


def _eleven_record_error(err: BaseException) -> None:
    global _eleven_consecutive_errors
    msg = str(err).lower()
    if any(p in msg for p in _ELEVEN_QUOTA_PATTERNS):
        _eleven_open_circuit(f"quota-like error: {msg[:120]}")
        return
    _eleven_consecutive_errors += 1
    if _eleven_consecutive_errors >= _ELEVEN_FAIL_THRESHOLD:
        _eleven_open_circuit(f"{_eleven_consecutive_errors} consecutive errors")


def _eleven_record_success() -> None:
    global _eleven_consecutive_errors
    _eleven_consecutive_errors = 0


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


def _strip_speaker_prefixes(named_text: str) -> str:
    lines: list[str] = []
    for line in named_text.splitlines():
        if ":" in line:
            lines.append(line.split(":", 1)[1].strip())
        else:
            lines.append(line.strip())
    return "\n".join(x for x in lines if x).strip()


async def _try_elevenlabs(
    audio: bytes,
    with_speaker_labels: bool,
    primary_speaker_name: str | None,
) -> str | None:
    try:
        result = await _elevenlabs_transcribe(audio)
    except Exception as e:
        logger.exception("ElevenLabs STT failed: %s", e)
        _eleven_record_error(e)
        return None

    if result is None:
        return None

    from elevenlabs.types import SpeechToTextChunkResponseModel
    from steward.helpers.transcription import build_named_speakers_text

    words = cast(SpeechToTextChunkResponseModel, result).words or []
    plain = (getattr(result, "text", "") or "").strip()

    text: str | None = None
    if with_speaker_labels and words:
        named = build_named_speakers_text(words, primary_speaker_name=primary_speaker_name)
        if named:
            text = named
    if text is None and plain:
        text = plain
    if text is None and not with_speaker_labels and words:
        named = build_named_speakers_text(words)
        if named:
            cleaned = _strip_speaker_prefixes(named)
            if cleaned:
                text = cleaned

    if text:
        _eleven_record_success()
    return text


_YANDEX_STT_SUBMIT_URL = "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
_YANDEX_OPERATION_URL = "https://operation.api.cloud.yandex.net/operations/{}"
_YANDEX_POLL_INTERVAL_SEC = 3.0
_YANDEX_POLL_MAX_ATTEMPTS = 80


def _yandex_stt_api_key() -> str | None:
    return os.environ.get("AI_STT_KEY") or os.environ.get("AI_KEY_SECRET")


def _extract_yandex_text(response: dict) -> str:
    refined: list[str] = []
    raw: list[str] = []

    for event in response.get("session_events") or []:
        if not isinstance(event, dict):
            continue
        normalized = ((event.get("final_refinement") or {}).get("normalized_text") or {})
        for alt in normalized.get("alternatives") or []:
            t = alt.get("text")
            if isinstance(t, str) and t.strip():
                refined.append(t.strip())
                break
        final = event.get("final") or {}
        for alt in final.get("alternatives") or []:
            t = alt.get("text")
            if isinstance(t, str) and t.strip():
                raw.append(t.strip())
                break

    chosen = refined or raw
    if chosen:
        return " ".join(chosen).strip()

    for ch in response.get("channel_results") or []:
        for r in ch.get("results") or []:
            holder = (
                (r.get("final_refinement") or {}).get("normalized_text")
                or r.get("final")
                or {}
            )
            for alt in holder.get("alternatives") or []:
                t = alt.get("text")
                if isinstance(t, str) and t.strip():
                    chosen.append(t.strip())
                    break
    if chosen:
        return " ".join(chosen).strip()

    def walk(node) -> None:
        if isinstance(node, dict):
            alts = node.get("alternatives")
            if isinstance(alts, list):
                for alt in alts:
                    if isinstance(alt, dict):
                        t = alt.get("text")
                        if isinstance(t, str) and t.strip():
                            chosen.append(t.strip())
                            return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(response)
    return " ".join(chosen).strip()


async def _yandex_transcribe(audio_mp3: bytes) -> str | None:
    api_key = _yandex_stt_api_key()
    if not api_key:
        return None

    body = {
        "content": base64.b64encode(audio_mp3).decode("ascii"),
        "recognition_model": {
            "model": "general",
            "audio_format": {
                "container_audio": {"container_audio_type": "MP3"}
            },
            "text_normalization": {
                "text_normalization": "TEXT_NORMALIZATION_ENABLED",
                "literature_text": True,
            },
            "language_restriction": {
                "restriction_type": "WHITELIST",
                "language_code": ["ru-RU"],
            },
            "audio_processing_type": "FULL_DATA",
        },
    }
    headers = {"Authorization": f"Api-Key {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(_YANDEX_STT_SUBMIT_URL, json=body, headers=headers)
            if r.status_code >= 400:
                logger.warning("Yandex STT submit HTTP %s: %s", r.status_code, r.text[:300])
                return None
            op = r.json() if isinstance(r.json(), dict) else {}
            op_id = op.get("id")
            if not op_id:
                logger.warning("Yandex STT response missing operation id: %s", op)
                return None

            op_url = _YANDEX_OPERATION_URL.format(op_id)
            for _ in range(_YANDEX_POLL_MAX_ATTEMPTS):
                await asyncio.sleep(_YANDEX_POLL_INTERVAL_SEC)
                op_r = await client.get(op_url, headers=headers)
                if op_r.status_code >= 400:
                    logger.warning(
                        "Yandex STT poll HTTP %s: %s", op_r.status_code, op_r.text[:300]
                    )
                    continue
                data = op_r.json()
                if not data.get("done"):
                    continue
                err = data.get("error")
                if err:
                    logger.warning("Yandex STT operation failed: %s", err)
                    return None
                response = data.get("response") or {}
                text = _extract_yandex_text(response)
                if not text:
                    logger.warning(
                        "Yandex STT done but no text extracted; response keys: %s",
                        list(response.keys()),
                    )
                return text or None
            logger.warning("Yandex STT polling timed out for operation %s", op_id)
            return None
    except Exception as e:
        logger.exception("Yandex STT failed: %s", e)
        return None


async def transcribe_audio_bytes(
    audio: bytes,
    *,
    with_speaker_labels: bool = False,
    primary_speaker_name: str | None = None,
) -> str | None:
    nv = await try_nvidia_transcribe_bytes(audio)
    if nv:
        return nv

    if _eleven_circuit_closed():
        text = await _try_elevenlabs(audio, with_speaker_labels, primary_speaker_name)
        if text:
            return text
    else:
        logger.info("ElevenLabs STT skipped: circuit open until %s", _eleven_open_until)

    return await _yandex_transcribe(audio)
