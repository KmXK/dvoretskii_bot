import asyncio
import logging
import os
import tempfile
from pathlib import Path

from telegram import InputFile

from steward.handlers.handler import Handler

logger = logging.getLogger(__name__)

VIDEO_PATH = Path("data/videos/stupid_video.mp4")
BG_AUDIO_PATH = Path("data/audio/lofi.mp3")

VIDEO_VARIANTS = [
    (1600.0, Path("data/videos/stupid_video_240p.mp4")),
    (360.0, Path("data/videos/stupid_video_480p.mp4")),
    (0.0, Path("data/videos/stupid_video_720p.mp4")),
]


def _pick_video(audio_dur: float) -> Path:
    for threshold, path in VIDEO_VARIANTS:
        if audio_dur >= threshold and path.exists():
            return path
    raise Exception(f"Invalid configuration: no video found for audio duration {audio_dur} seconds")


async def _get_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return float(stdout.decode().strip())


async def _run_ffmpeg(*args: str):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"ffmpeg failed: {stderr.decode()}")


class VoiceVideoHandler(Handler):
    VIDEO_OFFSET_KEY = "stupid_video"
    BG_AUDIO_OFFSET_KEY = "lofi_audio"

    async def chat(self, context):
        if not context.message.voice:
            return False
        if not VIDEO_PATH.exists():
            logger.warning("VoiceVideoHandler skipped: %s not found", VIDEO_PATH)
            return False

        try:
            tg_file = await context.bot.get_file(context.message.voice.file_id)
            if not tg_file.file_path:
                raise Exception("File path is not available")

            fp = tg_file.file_path
            if "/file/bot" in fp:
                fp = fp.split("/file/bot", 1)[1].split("/", 1)[1]
            audio_path = Path(f"/data/{context.bot.token}/{fp}")
            if not audio_path.exists():
                raise Exception(f"File not found: {audio_path}")

            tasks = [_get_duration(audio_path), _get_duration(VIDEO_PATH)]
            has_bg = BG_AUDIO_PATH.exists()
            if has_bg:
                tasks.append(_get_duration(BG_AUDIO_PATH))

            durations = await asyncio.gather(*tasks)
            audio_dur, video_dur = durations[0], durations[1]
            bg_dur = durations[2] if has_bg else None

            needed = audio_dur + 1.0
            if needed >= video_dur:
                await context.message.reply_text("Голосовое длиннее доступного видео, не могу ответить :(")
                return True

            video_path = _pick_video(audio_dur)

            video_start = self._pick_offset(self.VIDEO_OFFSET_KEY, needed, video_dur)
            bg_start = self._pick_offset(self.BG_AUDIO_OFFSET_KEY, needed, bg_dur) if bg_dur else None

            fd, out_path = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            try:
                await self._render(video_path, video_start, needed, audio_path, out_path, bg_start)
                self._update_offset(self.VIDEO_OFFSET_KEY, video_start + needed, video_dur)
                if bg_dur and bg_start is not None:
                    self._update_offset(self.BG_AUDIO_OFFSET_KEY, bg_start + needed, bg_dur)
                await self.repository.save()

                with open(out_path, "rb") as f:
                    await context.message.reply_video(InputFile(f, filename="reply.mp4"))
            finally:
                os.unlink(out_path)

            return True
        except Exception as e:
            logger.exception("Error processing voice message: %s", e)
            await context.message.reply_text("Ошибка при обработке голосового сообщения")
            return True

    def _pick_offset(self, key: str, needed: float, total: float) -> float:
        start = self.repository.db.data_offsets.get(key, 0.0)
        return 0.0 if start >= total or total - start < needed else start

    def _update_offset(self, key: str, val: float, total: float):
        self.repository.db.data_offsets[key] = val if val < total else 0.0

    async def _render(self, video: Path, start: float, dur: float, audio: Path, out: str, bg_start: float | None):
        if bg_start is not None:
            fd, mixed_audio = tempfile.mkstemp(suffix=".aac")
            os.close(fd)
            try:
                await _run_ffmpeg(
                    "-i", str(audio),
                    "-ss", str(bg_start), "-t", str(dur), "-i", str(BG_AUDIO_PATH),
                    "-filter_complex", "[1:a]volume=0.05[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
                    "-map", "[a]", "-c:a", "aac", mixed_audio,
                )
                await _run_ffmpeg(
                    "-ss", str(start), "-i", str(video),
                    "-i", mixed_audio,
                    "-map", "0:v", "-map", "1:a",
                    "-t", str(dur), "-c", "copy", out,
                )
            finally:
                os.unlink(mixed_audio)
        else:
            await _run_ffmpeg(
                "-ss", str(start), "-i", str(video),
                "-i", str(audio),
                "-map", "0:v", "-map", "1:a",
                "-t", str(dur), "-c:v", "copy", "-c:a", "aac", out,
            )
