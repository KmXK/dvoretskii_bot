import asyncio
import logging
import math
import os
import tempfile
from pathlib import Path

from pyrate_limiter import BucketFullException
from telegram import InputFile

from steward.helpers.limiter import Duration, check_limit
from steward.helpers.media import ffprobe_duration, run_ffmpeg

logger = logging.getLogger(__name__)

get_duration = ffprobe_duration

VIDEO_PATH = Path("data/videos/stupid_video.mp4")
BG_AUDIO_PATH = Path("data/audio/lofi.mp3")
VOICE_DAILY_LIMIT_SECONDS = 10 * 60

VIDEO_VARIANTS = [
    (1600.0, Path("data/videos/stupid_video_240p.mp4")),
    (360.0, Path("data/videos/stupid_video_480p.mp4")),
    (0.0, Path("data/videos/stupid_video_720p.mp4")),
]


def pick_video(audio_dur: float) -> Path:
    for threshold, path in VIDEO_VARIANTS:
        if audio_dur >= threshold and path.exists():
            return path
    raise Exception(
        f"Invalid configuration: no video found for audio duration {audio_dur} seconds"
    )


async def render_video(
    video: Path,
    start: float,
    dur: float,
    audio: Path,
    out: str,
    bg_start: float | None,
):
    if bg_start is not None:
        fd, mixed_audio = tempfile.mkstemp(suffix=".aac")
        os.close(fd)
        try:
            await run_ffmpeg(
                "-i",
                str(audio),
                "-ss",
                str(bg_start),
                "-t",
                str(dur),
                "-i",
                str(BG_AUDIO_PATH),
                "-filter_complex",
                "[1:a]volume=0.05[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
                "-map",
                "[a]",
                "-c:a",
                "aac",
                mixed_audio,
            )
            await run_ffmpeg(
                "-ss",
                str(start),
                "-i",
                str(video),
                "-i",
                mixed_audio,
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-t",
                str(dur),
                "-c",
                "copy",
                out,
            )
        finally:
            os.unlink(mixed_audio)
    else:
        await run_ffmpeg(
            "-ss",
            str(start),
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-t",
            str(dur),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            out,
        )


async def create_video_reply(
    feature,
    reply_target,
    audio_path: Path,
    user_id: int,
    video_offset_key: str,
    bg_audio_offset_key: str,
):
    if not VIDEO_PATH.exists():
        logger.warning("Voice video skipped: %s not found", VIDEO_PATH)
        await reply_target.reply_text("Видео временно недоступно")
        return

    tasks = [get_duration(audio_path), get_duration(VIDEO_PATH)]
    has_bg = BG_AUDIO_PATH.exists()
    if has_bg:
        tasks.append(get_duration(BG_AUDIO_PATH))

    durations = await asyncio.gather(*tasks)
    audio_dur, video_dur = durations[0], durations[1]
    bg_dur = durations[2] if has_bg else None

    needed = audio_dur + 1.0
    if needed >= video_dur:
        await reply_target.reply_text(
            "Голосовое длиннее доступного видео, не могу ответить :("
        )
        return

    try:
        check_limit(
            "voice_video_daily_seconds",
            VOICE_DAILY_LIMIT_SECONDS,
            24 * Duration.HOUR,
            name=str(user_id),
            weight=max(1, math.ceil(audio_dur)),
        )
    except BucketFullException:
        await reply_target.reply_text(
            "Лимит на голосовые исчерпан: 10 минут в сутки на пользователя."
        )
        return

    video_path = pick_video(audio_dur)
    video_start = _pick_offset(feature.repository, video_offset_key, needed, video_dur)
    bg_start = (
        _pick_offset(feature.repository, bg_audio_offset_key, needed, bg_dur)
        if bg_dur
        else None
    )

    fd, out_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        await render_video(
            video_path, video_start, needed, audio_path, out_path, bg_start
        )
        _update_offset(feature.repository, video_offset_key, video_start + needed, video_dur)
        if bg_dur and bg_start is not None:
            _update_offset(
                feature.repository, bg_audio_offset_key, bg_start + needed, bg_dur
            )
        await feature.repository.save()

        with open(out_path, "rb") as f:
            await reply_target.reply_video(InputFile(f, filename="reply.mp4"))
    finally:
        os.unlink(out_path)


def _pick_offset(repository, key: str, needed: float, total: float) -> float:
    start = repository.db.data_offsets.get(key, 0.0)
    return 0.0 if start >= total or total - start < needed else start


def _update_offset(repository, key: str, val: float, total: float):
    repository.db.data_offsets[key] = val if val < total else 0.0
