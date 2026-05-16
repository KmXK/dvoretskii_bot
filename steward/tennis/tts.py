"""TTS-озвучка для теннисного табло. Yandex SpeechKit → OGG/Opus в Telegram.

Всё опционально: если ключи не настроены или апи не отвечает — функция возвращает
None, и вызывающий код просто пропускает озвучку, не падая.
"""
from __future__ import annotations

import base64
import json as _json
import logging
import os

import httpx

from steward.data.models.tennis import TennisMatch, TennisSession
from steward.tennis.engine import SIDE_A, session_wins

logger = logging.getLogger(__name__)

_YANDEX_TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
_YANDEX_TTS_V3_URL = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
_REQUEST_TIMEOUT_SEC = 15.0
_DEFAULT_VOICE = "alena"
_DEFAULT_LANG = "ru-RU"


def _yandex_api_key() -> str | None:
    return (
        os.environ.get("TENNIS_TTS_KEY")
        or os.environ.get("AI_TTS_KEY")
        or os.environ.get("AI_KEY_SECRET")
    )


def _spoken_name(display: str, fallback: str) -> str:
    raw = (display or "").strip()
    if not raw or raw.startswith("id"):
        return fallback
    return raw.lstrip("@")


def match_announcement_text(
    match: TennisMatch,
    winner_name: str,
    *,
    use_score: bool = True,
) -> str:
    if use_score and match.score_a is not None and match.score_b is not None:
        # Озвучиваем в порядке "победитель — проигравший"
        if match.winner == SIDE_A:
            winner_score, loser_score = match.score_a, match.score_b
        else:
            winner_score, loser_score = match.score_b, match.score_a
        return f"Партия! Победил {winner_name}. Счёт {winner_score} на {loser_score}."
    return f"Партия! Победил {winner_name}."


def session_end_announcement_text(
    session: TennisSession,
    name_a: str,
    name_b: str,
) -> str:
    wins_a, wins_b = session_wins(session)
    if wins_a == wins_b:
        return f"Сессия завершена. Ничья: {wins_a} на {wins_b}."
    if wins_a > wins_b:
        return f"Сессия завершена. Победил {name_a} со счётом {wins_a} на {wins_b}."
    return f"Сессия завершена. Победил {name_b} со счётом {wins_b} на {wins_a}."


async def _synthesize_v3(text: str, api_key: str, voice: str, folder_id: str) -> bytes | None:
    """Yandex SpeechKit v3 — neural voices, more natural sound.

    Uses the same API key as v1. Falls back silently if the account doesn't
    have v3 access enabled.
    """
    payload: dict = {
        "text": text,
        "outputAudioSpec": {"containerAudio": {"containerAudioType": "OGG_OPUS"}},
        "hints": [{"voice": voice}],
    }
    if folder_id:
        payload["folderId"] = folder_id
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SEC) as client:
            resp = await client.post(
                _YANDEX_TTS_V3_URL,
                headers={"Authorization": f"Api-Key {api_key}"},
                json=payload,
            )
    except Exception:
        return None
    if resp.status_code >= 400:
        logger.info("tennis TTS v3 HTTP %d: %s", resp.status_code, resp.text[:200])
        return None
    parts: list[bytes] = []
    for line in resp.text.strip().splitlines():
        try:
            chunk = _json.loads(line)
            b64 = chunk.get("result", {}).get("audioChunk", {}).get("data", "")
            if b64:
                parts.append(base64.b64decode(b64))
        except Exception:
            pass
    return b"".join(parts) or None


async def synthesize(text: str) -> bytes | None:
    """Возвращает OGG/Opus-аудио для send_voice или None при любой неудаче.

    Пробует v3 (нейросетевые голоса) первой; при неудаче откатывается на v1.
    Можно принудительно отключить v3 через TENNIS_TTS_V3=0.
    """
    api_key = _yandex_api_key()
    if not api_key or not text.strip():
        return None
    voice = os.environ.get("TENNIS_TTS_VOICE", _DEFAULT_VOICE)
    folder_id = os.environ.get("AI_FOLDER_ID", "")

    if os.environ.get("TENNIS_TTS_V3", "1") != "0":
        result = await _synthesize_v3(text, api_key, voice, folder_id)
        if result:
            return result
        logger.info("tennis TTS v3 failed, falling back to v1")

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SEC) as client:
            response = await client.post(
                _YANDEX_TTS_URL,
                headers={"Authorization": f"Api-Key {api_key}"},
                data={
                    "text": text,
                    "lang": _DEFAULT_LANG,
                    "voice": voice,
                    "format": "oggopus",
                    "folderId": folder_id,
                },
            )
    except httpx.HTTPError as e:
        logger.info("tennis TTS v1 transport error: %s", e)
        return None
    except Exception:
        logger.exception("tennis TTS unexpected error")
        return None

    if response.status_code >= 400:
        logger.info(
            "tennis TTS v1 HTTP %d: %s",
            response.status_code,
            response.text[:200],
        )
        return None
    audio = response.content
    if not audio:
        return None
    return audio
