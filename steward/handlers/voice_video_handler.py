import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from moviepy.audio.AudioClip import CompositeAudioClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram import InputFile

from steward.handlers.handler import Handler

logger = logging.getLogger(__name__)


def _extract_file_path(file_path: str) -> str:
    if file_path.startswith("http://") or file_path.startswith("https://"):
        parsed_url = urlparse(file_path)
        path = parsed_url.path
        if path.startswith("/file/bot"):
            file_path = path[len("/file/bot") :]
            first_slash_idx = file_path.find("/")
            if first_slash_idx > 0:
                file_path = file_path[first_slash_idx + 1 :]
        else:
            file_path = path.lstrip("/")
    return file_path


class VoiceVideoHandler(Handler):
    VIDEO_PATH = Path("data/videos/stupid_video.mp4")
    BACKGROUND_AUDIO_PATH = Path("data/audio/lofi.mp3")
    VIDEO_OFFSET_KEY = "stupid_video"
    BACKGROUND_AUDIO_OFFSET_KEY = "lofi_audio"

    async def chat(self, context):
        voice = context.message.voice
        if voice is None:
            return False

        if not self.VIDEO_PATH.exists():
            logger.warning("VoiceVideoHandler skipped: %s not found", self.VIDEO_PATH)
            return False

        try:
            tg_file = await context.bot.get_file(voice.file_id)
            file_path = tg_file.file_path
            if not file_path:
                raise Exception("File path is not available")

            file_path = _extract_file_path(file_path)
            token = context.bot.token
            local_file_path = Path(f"/data/{token}/{file_path}")

            with tempfile.TemporaryDirectory(prefix="voice_video_") as tmp_dir:
                tmp_dir_path = Path(tmp_dir)
                audio_path = tmp_dir_path / "voice.ogg"

                if not local_file_path.exists():
                    raise Exception(f"File not found: {file_path}")

                shutil.copy2(local_file_path, audio_path)

                audio_duration = await asyncio.to_thread(
                    self._get_audio_duration, audio_path
                )

                video_duration = await asyncio.to_thread(self._get_video_duration)
                if audio_duration + 1.0 >= video_duration:
                    await context.message.reply_text(
                        "Голосовое длиннее доступного видео, не могу ответить :("
                    )
                    return True

                start_position = self._pick_start_position(
                    audio_duration, video_duration
                )

                bg_audio_duration = None
                if self.BACKGROUND_AUDIO_PATH.exists():
                    bg_audio_duration = await asyncio.to_thread(
                        self._get_audio_duration, self.BACKGROUND_AUDIO_PATH
                    )

                merged_path = tmp_dir_path / "merged.mp4"

                bg_audio_start = None
                if bg_audio_duration is not None:
                    bg_audio_start = self._pick_background_audio_start_position(
                        audio_duration + 1.0, bg_audio_duration
                    )

                await asyncio.to_thread(
                    self._render_video,
                    start_position,
                    audio_duration,
                    audio_path,
                    merged_path,
                    bg_audio_duration,
                    bg_audio_start,
                )

                self._store_new_offset(start_position, audio_duration, video_duration)
                if bg_audio_duration is not None and bg_audio_start is not None:
                    self._store_background_audio_offset(
                        bg_audio_start, audio_duration, bg_audio_duration
                    )
                await self.repository.save()

                with merged_path.open("rb") as final_file:
                    await context.message.reply_video(
                        InputFile(final_file, filename="reply.mp4")
                    )

            return True
        except Exception as e:
            logger.exception("Error processing voice message: %s", e)
            await context.message.reply_text(
                "Ошибка при обработке голосового сообщения"
            )
            return True

    def _pick_start_position(
        self, audio_duration: float, video_duration: float
    ) -> float:
        start = self.repository.db.data_offsets.get(self.VIDEO_OFFSET_KEY, 0.0)
        if start >= video_duration:
            start = 0.0

        video_duration_needed = audio_duration + 1.0
        remaining = video_duration - start
        if remaining < video_duration_needed:
            start = 0.0

        return start

    def _store_new_offset(self, start: float, duration: float, video_duration: float):
        new_offset = start + duration + 1.0
        if new_offset >= video_duration:
            new_offset = 0.0
        self.repository.db.data_offsets[self.VIDEO_OFFSET_KEY] = new_offset

    def _pick_background_audio_start_position(
        self, video_duration_needed: float, bg_audio_duration: float
    ) -> float:
        """Выбирает стартовую позицию для фонового аудио с проверкой, что его хватит"""
        start = self.repository.db.data_offsets.get(
            self.BACKGROUND_AUDIO_OFFSET_KEY, 0.0
        )
        if start >= bg_audio_duration:
            start = 0.0

        remaining = bg_audio_duration - start
        if remaining < video_duration_needed:
            start = 0.0

        return start

    def _store_background_audio_offset(
        self, start: float, duration: float, bg_audio_duration: float
    ):
        new_offset = start + duration + 1.0
        if new_offset >= bg_audio_duration:
            new_offset = 0.0
        self.repository.db.data_offsets[self.BACKGROUND_AUDIO_OFFSET_KEY] = new_offset

    def _get_audio_duration(self, path: Path) -> float:
        with AudioFileClip(str(path)) as clip:
            return clip.duration

    def _get_video_duration(self) -> float:
        with VideoFileClip(str(self.VIDEO_PATH)) as clip:
            return clip.duration

    def _render_video(
        self,
        start: float,
        duration: float,
        audio_path: Path,
        output_path: Path,
        bg_audio_duration: float | None = None,
        bg_audio_start: float | None = None,
    ):
        with VideoFileClip(str(self.VIDEO_PATH)) as video:
            with AudioFileClip(str(audio_path)) as audio:
                precise_audio_duration = audio.duration
                audio_clip = audio

                video_duration_needed = precise_audio_duration + 1.0
                video_end = min(start + video_duration_needed, video.duration)
                video_chunk = video.subclipped(start, video_end).without_audio()

                try:
                    bg_audio = None
                    if (
                        self.BACKGROUND_AUDIO_PATH.exists()
                        and bg_audio_duration is not None
                        and bg_audio_start is not None
                    ):
                        try:
                            bg_audio = AudioFileClip(str(self.BACKGROUND_AUDIO_PATH))
                            bg_audio_end = min(
                                bg_audio_start + video_duration_needed,
                                bg_audio_duration,
                            )
                            bg_audio_clip = bg_audio.subclipped(
                                bg_audio_start, bg_audio_end
                            )
                            bg_audio_clip = bg_audio_clip.with_volume_scaled(0.05)
                            bg_audio_clip = bg_audio_clip.with_start(0)
                            audio_clip_synced = audio_clip.with_start(0)
                            composite_audio = CompositeAudioClip(
                                [bg_audio_clip, audio_clip_synced]
                            )
                            final_clip = video_chunk.with_audio(composite_audio)
                        except Exception as e:
                            logger.warning("Failed to add background audio: %s", e)
                            if bg_audio is not None:
                                bg_audio.close()
                            final_clip = video_chunk.with_audio(audio_clip)
                    else:
                        final_clip = video_chunk.with_audio(audio_clip)

                    desired_duration = precise_audio_duration + 1.0
                    actual_duration = final_clip.duration
                    final_duration = min(desired_duration, actual_duration)

                    if final_duration < actual_duration and final_duration > 0:
                        final_clip = final_clip.subclipped(0, final_duration)
                    try:
                        final_clip.write_videofile(
                            str(output_path),
                            codec="libx264",
                            audio_codec="aac",
                            logger=None,
                        )
                    finally:
                        final_clip.close()
                        if bg_audio is not None:
                            bg_audio.close()
                finally:
                    video_chunk.close()
