"""Modal client for EchoMimicV2: animate the anchor cutout to the TTS audio.

The audio is split into ≤14-sec chunks (V2 with the bundled pose template caps at
~14 sec per call) and chunks are dispatched to the deployed Modal endpoint in
parallel. Resulting mp4 chunks are concatenated locally with ffmpeg.

The Modal app must be deployed (`modal deploy news_avatar/modal_echomimic.py`) —
this client looks it up by name (`echomimic-v2`).
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_APP = "echomimic-v2"
_CLS = "EchoMimicV2"


def _ogg_to_wav(ogg_bytes: bytes) -> bytes:
    proc = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0",
         "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"],
        input=ogg_bytes,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def _concat_mp4(parts: list[Path], out_path: Path) -> None:
    list_file = out_path.with_suffix(".concat.txt")
    list_file.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
    try:
        # Try stream copy first
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(list_file), "-c", "copy", str(out_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            # Re-encode if parts have differing params
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", str(list_file),
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                 str(out_path)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:500]}")
    finally:
        list_file.unlink(missing_ok=True)


def _get_infer():
    """Look up the deployed EchoMimicV2.infer remote function. Lazy-imports `modal`
    so the bot can start in environments without the SDK (falls back to static anchor).
    """
    import modal  # local import — optional dependency

    cls = modal.Cls.from_name(_APP, _CLS)
    return cls().infer


async def animate_anchor(
    *,
    image_bytes: bytes,
    audio_chunk_paths: list[Path],
    out_dir: Path,
    pose: str = "01",
    steps: int = 6,
) -> Path | None:
    """Animate anchor for each audio chunk in parallel, concat results to one mp4.

    image_bytes: anchor JPEG/PNG with black background (V2 reference image).
    audio_chunk_paths: list of OGG audio chunks (will be converted to WAV).
    out_dir: working directory.
    Returns path to combined mp4 (no audio track), or None on failure.
    """
    if not audio_chunk_paths:
        return None
    try:
        infer = _get_infer()
    except ImportError as e:
        logger.warning(
            "modal SDK import failed — skipping anchor animation: %s",
            e,
        )
        return None
    except Exception:
        logger.exception("failed to look up Modal echomimic-v2 endpoint")
        return None

    async def one(i: int, audio_path: Path) -> Path | None:
        try:
            wav_bytes = _ogg_to_wav(audio_path.read_bytes())
        except Exception:
            logger.exception("ogg→wav for chunk %d failed", i)
            return None
        try:
            video_bytes = await infer.remote.aio(
                image_bytes, wav_bytes, pose, 768, 768, steps, 1.0, 24, 420 + i,
            )
        except Exception:
            logger.exception("V2 inference for chunk %d failed", i)
            return None
        path = out_dir / f"anchor_{i:02d}.mp4"
        path.write_bytes(video_bytes)
        return path

    out_dir.mkdir(parents=True, exist_ok=True)
    results = await asyncio.gather(*(one(i, p) for i, p in enumerate(audio_chunk_paths)))
    parts = [p for p in results if p is not None]
    logger.info(
        "echomimic chunks: requested=%d, succeeded=%d, failed=%d",
        len(audio_chunk_paths), len(parts), len(audio_chunk_paths) - len(parts),
    )
    if not parts:
        return None

    if len(parts) == 1:
        return parts[0]

    final = out_dir / "anchor_concat.mp4"
    await asyncio.to_thread(_concat_mp4, parts, final)
    return final
