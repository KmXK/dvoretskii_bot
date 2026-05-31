"""Yandex SpeechKit TTS for news anchor — gruff male voice (madirus by default).

Yandex v3 sync endpoint caps single requests at ~250 chars. We split the script by
sentences, synthesize each chunk and concat via ffmpeg.

`synthesize_news` returns a TtsResult that exposes both the merged audio path
(used as soundtrack) and the per-chunk paths (used by the echomimic stage to
animate the anchor in matching segments).
"""
from __future__ import annotations

import asyncio
import base64
import json as _json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_YANDEX_TTS_V3_URL = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
_TIMEOUT = 30.0
_DEFAULT_VOICE = "madirus"
_CHUNK_LIMIT = 240


def _api_key() -> str | None:
    return (
        os.environ.get("NEWS_TTS_KEY")
        or os.environ.get("TENNIS_TTS_KEY")
        or os.environ.get("AI_TTS_KEY")
        or os.environ.get("AI_KEY_SECRET")
    )


def _split_into_chunks(text: str, limit: int = _CHUNK_LIMIT) -> list[str]:
    """Group sentences so each chunk ≤ limit chars. Respects sentence boundaries."""
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        # If a single sentence is over the limit, hard-wrap by spaces.
        if len(s) > limit:
            words = s.split()
            buf = ""
            for w in words:
                if len(buf) + len(w) + 1 > limit:
                    if buf:
                        chunks.append(buf.strip())
                    buf = w
                else:
                    buf = (buf + " " + w).strip()
            if buf:
                if cur:
                    chunks.append(cur.strip())
                    cur = ""
                chunks.append(buf)
            continue
        if not cur:
            cur = s
        elif len(cur) + 1 + len(s) <= limit:
            cur = cur + " " + s
        else:
            chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    return chunks


async def _tts_one(text: str, api_key: str, voice: str, folder_id: str) -> bytes | None:
    payload: dict = {
        "text": text,
        "outputAudioSpec": {"containerAudio": {"containerAudioType": "OGG_OPUS"}},
        "hints": [{"voice": voice}],
    }
    if folder_id:
        payload["folderId"] = folder_id
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _YANDEX_TTS_V3_URL,
                headers={"Authorization": f"Api-Key {api_key}"},
                json=payload,
            )
    except Exception:
        logger.exception("news TTS transport error")
        return None
    if resp.status_code >= 400:
        logger.warning("news TTS HTTP %d: %s", resp.status_code, resp.text[:300])
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
    audio = b"".join(parts)
    return audio or None


def _concat_ogg(parts: list[Path], out_path: Path) -> None:
    """Concat ogg files with ffmpeg. Writes raw concat in the same container."""
    # Use ffmpeg concat demuxer
    list_file = out_path.with_suffix(".txt")
    list_file.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        # Fallback: re-encode
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file.with_name(list_file.name)),
            "-c:a", "libopus", str(out_path),
        ]
        # Need to recreate list_file
        list_file.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c:a", "libopus", str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        list_file.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:500]}")


@dataclass
class TtsResult:
    full_path: Path
    chunk_paths: list[Path]
    chunk_durations: list[float]


def _probe_duration(path: Path) -> float:
    """Return the duration of an audio file in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip() or 0.0)


async def synthesize_per_slide(
    slide_texts: list[str],
    out_path: Path,
    *,
    voice: str | None = None,
    folder_id: str | None = None,
) -> TtsResult | None:
    """One TTS call per slide → chunk_paths align 1-to-1 with input slides.

    If a slide's text exceeds the 240-char Yandex limit, it's internally chunked
    and concatenated back so the result is still exactly one audio file per slide.
    Returns concatenated full audio + per-slide paths + per-slide durations.
    """
    api_key = _api_key()
    if not api_key or not slide_texts:
        logger.warning("news TTS: no api key or empty slides")
        return None
    voice = voice or os.environ.get("NEWS_TTS_VOICE", _DEFAULT_VOICE)
    folder_id = folder_id or os.environ.get("AI_FOLDER_ID", "")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    slide_paths: list[Path] = []
    for i, text in enumerate(slide_texts):
        if not text.strip():
            return None
        sub_chunks = _split_into_chunks(text)
        sub_paths: list[Path] = []
        for j, sub in enumerate(sub_chunks):
            audio = await _tts_one(sub, api_key, voice, folder_id)
            if audio is None:
                logger.warning("TTS slide %d sub-chunk %d failed: %r", i, j, sub[:80])
                return None
            sp = out_path.parent / f"_tts_s{i:02d}_p{j:02d}.ogg"
            sp.write_bytes(audio)
            sub_paths.append(sp)

        slide_path = out_path.parent / f"tts_slide_{i:02d}.ogg"
        if len(sub_paths) == 1:
            shutil.move(str(sub_paths[0]), str(slide_path))
        else:
            await asyncio.to_thread(_concat_ogg, sub_paths, slide_path)
            for sp in sub_paths:
                sp.unlink(missing_ok=True)
        slide_paths.append(slide_path)

    if len(slide_paths) == 1:
        shutil.copy(str(slide_paths[0]), str(out_path))
    else:
        await asyncio.to_thread(_concat_ogg, slide_paths, out_path)

    durations = [_probe_duration(p) for p in slide_paths]
    logger.info("news TTS per-slide: %d slides, durations=%s, total=%.2fs",
                len(slide_paths), [f"{d:.2f}" for d in durations], sum(durations))
    return TtsResult(full_path=out_path, chunk_paths=slide_paths, chunk_durations=durations)
