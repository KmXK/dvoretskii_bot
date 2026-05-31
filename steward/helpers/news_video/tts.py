"""TTS for news anchor — Yandex SpeechKit by default, optional ElevenLabs.

Yandex v3 sync endpoint caps single requests at ~250 chars. We split the script by
sentences, synthesize each chunk and concat via ffmpeg.

Set `NEWS_TTS_PROVIDER=elevenlabs` (+ `EVELEN_LABS_STT`/`ELEVENLABS_API_KEY` and
`NEWS_TTS_ELEVEN_VOICE_ID`) to route through ElevenLabs `eleven_multilingual_v2`.

`synthesize_per_sentence` returns a TtsResult that exposes the merged audio,
per-slide chunk paths (for V2 / slide-timing) and per-sentence durations (for
per-sentence anchor emotion swaps).
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
_ELEVEN_CHUNK_LIMIT = 4500  # ElevenLabs allows much longer single calls
_ELEVEN_DEFAULT_MODEL = "eleven_multilingual_v2"


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


def _eleven_key() -> str | None:
    return (
        os.environ.get("ELEVENLABS_API_KEY")
        or os.environ.get("EVELEN_LABS_STT")  # name used elsewhere in the project
    )


def _provider() -> str:
    p = os.environ.get("NEWS_TTS_PROVIDER", "yandex").strip().lower()
    return p if p in {"yandex", "elevenlabs"} else "yandex"


def _tts_one_eleven_sync(text: str, voice_id: str, model_id: str, api_key: str) -> bytes | None:
    """Sync call to ElevenLabs TTS, returns mp3 bytes."""
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(
        api_key=api_key,
        httpx_client=httpx.Client(timeout=120, proxy=os.environ.get("DOWNLOAD_PROXY")),
    )
    try:
        stream = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format="mp3_44100_128",
        )
        return b"".join(stream)
    except Exception:
        logger.exception("ElevenLabs TTS call failed")
        return None


async def list_eleven_voices() -> list[dict] | None:
    """List voices available on the configured ElevenLabs account.

    Returns a list of dicts: [{voice_id, name, gender, age, category, description}].
    Use this to find voice IDs that actually work on the current plan — free-tier
    accounts can only call voices that already sit in 'My Voices', so this is the
    safest way to enumerate them.
    """
    api_key = _eleven_key()
    if not api_key:
        logger.warning("ElevenLabs list: no API key set")
        return None

    def _fetch() -> list[dict]:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(
            api_key=api_key,
            httpx_client=httpx.Client(timeout=60, proxy=os.environ.get("DOWNLOAD_PROXY")),
        )
        resp = client.voices.get_all()
        out: list[dict] = []
        for v in getattr(resp, "voices", []) or []:
            labels = getattr(v, "labels", None) or {}
            out.append({
                "voice_id": getattr(v, "voice_id", ""),
                "name": getattr(v, "name", ""),
                "gender": labels.get("gender", ""),
                "age": labels.get("age", ""),
                "category": getattr(v, "category", ""),
                "description": labels.get("description", "") or labels.get("descriptive", ""),
            })
        return out

    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        logger.exception("ElevenLabs voice list failed")
        return None


async def synthesize_eleven_test(text: str, voice_id: str, out_path: Path) -> Path | None:
    """One-shot ElevenLabs synth for admin voice-testing (the /tts command).

    Always uses ElevenLabs regardless of NEWS_TTS_PROVIDER. Writes OGG/Opus to
    out_path so the caller can send it as a Telegram voice message.
    """
    api_key = _eleven_key()
    if not api_key:
        logger.warning("ElevenLabs test: no API key set")
        return None
    if not text.strip() or not voice_id.strip():
        return None
    model_id = os.environ.get("NEWS_TTS_ELEVEN_MODEL", _ELEVEN_DEFAULT_MODEL)
    mp3 = await asyncio.to_thread(_tts_one_eleven_sync, text, voice_id, model_id, api_key)
    if mp3 is None:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = await asyncio.to_thread(_mp3_to_ogg, mp3, out_path)
    return out_path if ok else None


async def _tts_one_eleven(text: str) -> bytes | None:
    api_key = _eleven_key()
    if not api_key:
        logger.warning("ElevenLabs TTS: no API key (ELEVENLABS_API_KEY / EVELEN_LABS_STT)")
        return None
    voice_id = os.environ.get("NEWS_TTS_ELEVEN_VOICE_ID")
    if not voice_id:
        logger.warning("ElevenLabs TTS: NEWS_TTS_ELEVEN_VOICE_ID not set")
        return None
    model_id = os.environ.get("NEWS_TTS_ELEVEN_MODEL", _ELEVEN_DEFAULT_MODEL)
    return await asyncio.to_thread(_tts_one_eleven_sync, text, voice_id, model_id, api_key)


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
    # Per-slide audio files (used by EchoMimicV2 and as the source for chunk_durations).
    chunk_paths: list[Path]
    chunk_durations: list[float]
    # Per-slide list of per-sentence durations (sum equals the slide's chunk_duration).
    # Populated by synthesize_per_sentence; empty list per slide when sentence info is absent.
    sentence_durations: list[list[float]] | None = None


def _probe_duration(path: Path) -> float:
    """Return the duration of an audio file in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip() or 0.0)


def _mp3_to_ogg(mp3: bytes, dst: Path) -> bool:
    """Convert mp3 bytes (ElevenLabs output) to OGG/Opus on disk so all downstream
    concat/duration logic is uniform regardless of provider."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", "pipe:0",
         "-c:a", "libopus", "-b:a", "64k", str(dst)],
        input=mp3, capture_output=True,
    )
    return result.returncode == 0


async def _synth_one_sentence(
    text: str, dst: Path, *, yandex_key: str | None, voice: str, folder_id: str,
) -> bool:
    """Synthesize one sentence with the currently selected provider; write OGG to dst."""
    provider = _provider()
    if provider == "elevenlabs":
        mp3 = await _tts_one_eleven(text)
        if mp3 is None:
            return False
        return await asyncio.to_thread(_mp3_to_ogg, mp3, dst)
    # Yandex (default): one sentence may exceed 240-char limit, chunk if needed.
    if yandex_key is None:
        return False
    sub_chunks = _split_into_chunks(text)
    if len(sub_chunks) == 1:
        audio = await _tts_one(sub_chunks[0], yandex_key, voice, folder_id)
        if audio is None:
            return False
        dst.write_bytes(audio)
        return True
    sub_paths: list[Path] = []
    for k, sub in enumerate(sub_chunks):
        audio = await _tts_one(sub, yandex_key, voice, folder_id)
        if audio is None:
            for sp in sub_paths:
                sp.unlink(missing_ok=True)
            return False
        sp = dst.parent / f"{dst.stem}_sub{k:02d}.ogg"
        sp.write_bytes(audio)
        sub_paths.append(sp)
    await asyncio.to_thread(_concat_ogg, sub_paths, dst)
    for sp in sub_paths:
        sp.unlink(missing_ok=True)
    return True


async def synthesize_per_sentence(
    slides_sentences: list[list[str]],
    out_path: Path,
    *,
    voice: str | None = None,
    folder_id: str | None = None,
) -> TtsResult | None:
    """One TTS call per sentence, grouped into per-slide audio files.

    Returns TtsResult with per-slide chunks (for V2 + slide-image timing) and
    per-sentence durations within each slide (for per-sentence emotion overlay).
    """
    provider = _provider()
    yandex_key = _api_key() if provider == "yandex" else None
    if provider == "yandex" and not yandex_key:
        logger.warning("news TTS yandex: no api key")
        return None
    if provider == "elevenlabs":
        missing = []
        if not _eleven_key():
            missing.append("ELEVENLABS_API_KEY or EVELEN_LABS_STT")
        if not os.environ.get("NEWS_TTS_ELEVEN_VOICE_ID"):
            missing.append("NEWS_TTS_ELEVEN_VOICE_ID")
        if missing:
            logger.warning("news TTS elevenlabs: missing env vars: %s", ", ".join(missing))
            return None
    if not slides_sentences:
        return None

    voice = voice or os.environ.get("NEWS_TTS_VOICE", _DEFAULT_VOICE)
    folder_id = folder_id or os.environ.get("AI_FOLDER_ID", "")
    logger.info("news TTS: provider=%s", provider)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    slide_paths: list[Path] = []
    sentence_durations: list[list[float]] = []

    for i, sentences in enumerate(slides_sentences):
        if not sentences:
            return None
        sentence_paths: list[Path] = []
        for j, sent in enumerate(sentences):
            sent = (sent or "").strip()
            if not sent:
                return None
            sent_path = out_path.parent / f"tts_s{i:02d}_t{j:02d}.ogg"
            ok = await _synth_one_sentence(
                sent, sent_path, yandex_key=yandex_key, voice=voice, folder_id=folder_id,
            )
            if not ok:
                logger.warning("TTS slide %d sent %d failed: %r", i, j, sent[:80])
                return None
            sentence_paths.append(sent_path)

        slide_path = out_path.parent / f"tts_slide_{i:02d}.ogg"
        if len(sentence_paths) == 1:
            shutil.copy(str(sentence_paths[0]), str(slide_path))
        else:
            await asyncio.to_thread(_concat_ogg, sentence_paths, slide_path)
        slide_paths.append(slide_path)
        sentence_durations.append([_probe_duration(p) for p in sentence_paths])

    if len(slide_paths) == 1:
        shutil.copy(str(slide_paths[0]), str(out_path))
    else:
        await asyncio.to_thread(_concat_ogg, slide_paths, out_path)

    slide_durations = [_probe_duration(p) for p in slide_paths]
    logger.info(
        "news TTS: %d slides, %d sentences total, slide durations=%s, total=%.2fs",
        len(slide_paths),
        sum(len(s) for s in sentence_durations),
        [f"{d:.2f}" for d in slide_durations],
        sum(slide_durations),
    )
    return TtsResult(
        full_path=out_path,
        chunk_paths=slide_paths,
        chunk_durations=slide_durations,
        sentence_durations=sentence_durations,
    )


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
