import base64
import logging
import os
import tempfile
from pathlib import Path

from steward.helpers.ai import make_yandex_vlm_describe
from steward.helpers.media import ffprobe_duration, run_ffmpeg

logger = logging.getLogger(__name__)

_MAX_FRAMES = 6
_FRAME_LONG_EDGE = 256
_JPEG_QUALITY = 6  # ffmpeg -q:v scale; 6 ≈ JPEG q~70, tiny files
_SCENE_THRESHOLD = 0.22
_SHORT_VIDEO_SEC = 4.0  # below this we skip scene detection and grab a single middle frame
_MIN_INTERVAL_SEC = 6.0

# MJPEG encoder requires full-range YUV; without format=yuvj420p ffmpeg fails
# with "Non full-range YUV is non-standard" on many TV-range sources (Telegram кружки).
_JPEG_FORMAT_SUFFIX = ",format=yuvj420p"
_SCALE = f"scale='min({_FRAME_LONG_EDGE},iw)':-2"

_VLM_PROMPT = (
    "Это кадры из короткого видеосообщения (video note) в Telegram, по порядку. "
    "Опиши в 1-2 коротких предложениях то, что визуально происходит: обстановку, "
    "действия, выражение лица, заметные детали. Без воды, без кавычек, без форматирования."
)


async def _probe_duration(video_path: Path) -> float:
    try:
        return await ffprobe_duration(video_path)
    except Exception:
        return 0.0


async def _extract_middle_frame(video_path: Path, out_dir: Path, duration: float) -> list[Path]:
    single = out_dir / "mid.jpg"
    args: list[str] = []
    if duration > 0:
        args += ["-ss", f"{duration / 2:.3f}"]
    args += [
        "-i", str(video_path),
        "-vf", _SCALE + _JPEG_FORMAT_SUFFIX,
        "-frames:v", "1",
        "-q:v", str(_JPEG_QUALITY),
        str(single),
    ]
    try:
        await run_ffmpeg(*args)
    except Exception as e:
        logger.warning("Single-frame extraction failed: %s", e)
        return []
    return [single] if single.exists() else []


async def _extract_scene_frames(video_path: Path, out_dir: Path) -> list[Path]:
    pattern = str(out_dir / "scene_%03d.jpg")
    vf = (
        f"select='gt(scene,{_SCENE_THRESHOLD})',"
        f"{_SCALE}{_JPEG_FORMAT_SUFFIX}"
    )
    try:
        await run_ffmpeg(
            "-i", str(video_path),
            "-vf", vf,
            "-fps_mode", "vfr",
            "-q:v", str(_JPEG_QUALITY),
            "-frames:v", str(_MAX_FRAMES),
            pattern,
        )
    except Exception as e:
        logger.warning("Scene frame extraction failed: %s", e)
        return []
    return sorted(out_dir.glob("scene_*.jpg"))[:_MAX_FRAMES]


async def _extract_interval_frames(
    video_path: Path, out_dir: Path, duration: float
) -> list[Path]:
    interval = max(_MIN_INTERVAL_SEC, duration / _MAX_FRAMES)
    pattern = str(out_dir / "int_%03d.jpg")
    vf = f"fps=1/{interval:.3f},{_SCALE}{_JPEG_FORMAT_SUFFIX}"
    try:
        await run_ffmpeg(
            "-i", str(video_path),
            "-vf", vf,
            "-q:v", str(_JPEG_QUALITY),
            "-frames:v", str(_MAX_FRAMES),
            pattern,
        )
    except Exception as e:
        logger.warning("Interval frame extraction failed: %s", e)
        return []
    return sorted(out_dir.glob("int_*.jpg"))[:_MAX_FRAMES]


async def _extract_frames(video_path: Path, out_dir: Path) -> list[Path]:
    duration = await _probe_duration(video_path)

    if 0 < duration <= _SHORT_VIDEO_SEC:
        return await _extract_middle_frame(video_path, out_dir, duration)

    frames = await _extract_scene_frames(video_path, out_dir)
    if frames:
        return frames

    if duration > 0:
        frames = await _extract_interval_frames(video_path, out_dir, duration)
        if frames:
            return frames

    return await _extract_middle_frame(video_path, out_dir, duration)


async def describe_video(video_path: Path) -> str | None:
    """Extract a few representative frames from the video and describe them via Yandex VLM.

    Returns None if Yandex is not configured, extraction fails, or the model returns empty.
    """
    if not os.environ.get("AI_KEY_SECRET"):
        logger.debug("Visual description skipped: AI_KEY_SECRET is not set")
        return None

    with tempfile.TemporaryDirectory(prefix="vlm_frames_") as tmp_dir:
        out_dir = Path(tmp_dir)
        frames = await _extract_frames(video_path, out_dir)
        if not frames:
            logger.warning("No frames extracted from %s", video_path)
            return None

        images_b64: list[str] = []
        for fp in frames:
            try:
                images_b64.append(base64.standard_b64encode(fp.read_bytes()).decode("ascii"))
            except Exception as e:
                logger.warning("Failed to read frame %s: %s", fp, e)
        if not images_b64:
            return None

        try:
            text = await make_yandex_vlm_describe(0, _VLM_PROMPT, images_b64, max_tokens=200)
        except Exception as e:
            logger.exception("VLM describe failed: %s", e)
            return None

        clean = (text or "").strip()
        return clean or None
