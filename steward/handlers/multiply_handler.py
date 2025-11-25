import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from moviepy.audio.io.AudioFileClip import AudioFileClip
from telegram import InputFile

from steward.helpers.command_validation import validate_command_msg
from steward.helpers.tg_update_helpers import get_message
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step

logger = logging.getLogger(__name__)

MAX_VOICE_DURATION = 600


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


class CollectVoiceStep(Step):
    """Шаг для получения голосового сообщения"""

    def __init__(self, name):
        self.name = name
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            await context.message.reply_text(
                "Отправьте мне голосовое сообщение, которое нужно повторить"
            )
            self.is_waiting = True
            return False

        if not context.message.voice:
            await context.message.reply_text(
                "Это не голосовое сообщение. Пожалуйста, отправьте голосовое сообщение."
            )
            return False

        voice = context.message.voice
        try:
            tg_file = await context.bot.get_file(voice.file_id)
            file_path = tg_file.file_path
            if not file_path:
                raise Exception("File path is not available")

            file_path = _extract_file_path(file_path)
            token = context.bot.token
            local_file_path = Path(f"/data/{token}/{file_path}")

            with tempfile.TemporaryDirectory(prefix="multiply_voice_temp_") as tmp_dir:
                tmp_dir_path = Path(tmp_dir)
                audio_path = tmp_dir_path / "voice.ogg"

                if not local_file_path.exists():
                    raise Exception(f"File not found: {file_path}")

                shutil.copy2(local_file_path, audio_path)

                audio_duration = await asyncio.to_thread(
                    self._get_audio_duration, audio_path
                )

                context.session_context[self.name] = {
                    "voice": voice,
                    "duration": audio_duration,
                }
                context.session_context["bot"] = context.bot

        except Exception as e:
            logger.exception("Error getting voice duration: %s", e)
            await context.message.reply_text(
                "Ошибка при обработке голосового сообщения"
            )
            return False

        self.is_waiting = False
        return True

    async def callback(self, context):
        return False

    def stop(self):
        self.is_waiting = False

    def _get_audio_duration(self, path: Path) -> float:
        with AudioFileClip(str(path)) as clip:
            return clip.duration


class CollectCountStep(Step):
    """Шаг для получения количества повторений"""

    def __init__(self, name):
        self.name = name
        self.is_waiting = False
        self.voice_duration: float | None = None

    async def chat(self, context):
        if not self.is_waiting:
            voice_info = context.session_context.get("voice_info", {})
            self.voice_duration = voice_info.get("duration")

            if self.voice_duration is None:
                await context.message.reply_text(
                    "Ошибка: не удалось определить длительность голосового сообщения"
                )
                return True

            max_count = int(MAX_VOICE_DURATION / self.voice_duration)
            if max_count < 1:
                await context.message.reply_text(
                    f"Голосовое сообщение слишком длинное (больше {MAX_VOICE_DURATION // 60} минут). "
                    "Не могу создать повторение."
                )
                return True

            await context.message.reply_text(
                f"Сколько раз повторить голосовое сообщение? "
                f"(максимум {max_count} раз, чтобы не превысить {MAX_VOICE_DURATION // 60} минут)"
            )
            self.is_waiting = True
            return False

        if not context.message.text:
            await context.message.reply_text(
                "Пожалуйста, введите число (количество повторений)"
            )
            return False

        try:
            count = int(context.message.text)

            if count < 1:
                await context.message.reply_text(
                    "Количество повторений должно быть больше 0"
                )
                return False

            if self.voice_duration is None:
                await context.message.reply_text(
                    "Ошибка: не удалось определить длительность голосового сообщения"
                )
                return True

            max_count = int(MAX_VOICE_DURATION / self.voice_duration)
            if count > max_count:
                await context.message.reply_text(
                    f"Слишком много повторений. Максимум {max_count} раз "
                    f"(чтобы не превысить {MAX_VOICE_DURATION // 60} минут)"
                )
                return False

            context.session_context[self.name] = count
            self.is_waiting = False
            return True

        except ValueError:
            await context.message.reply_text(
                "Неверный формат. Пожалуйста, введите целое число (например, 3)"
            )
            return False

    async def callback(self, context):
        return False

    def stop(self):
        self.is_waiting = False


class MultiplyHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                CollectVoiceStep("voice_info"),
                CollectCountStep("count"),
            ]
        )

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "multiply"):
            return False

        assert update.message and update.message.text
        parts = update.message.text.split()
        if len(parts) > 1:
            return False

        return True

    async def on_session_finished(self, update, session_context):
        voice_info = session_context.get("voice_info", {})
        count = session_context.get("count")

        if not voice_info.get("voice") or count is None:
            await get_message(update).chat.send_message(
                "Ошибка: не удалось получить необходимые данные"
            )
            return

        bot = session_context.get("bot")
        if bot is None:
            await get_message(update).chat.send_message(
                "Ошибка: не удалось получить бота"
            )
            return

        try:
            voice = voice_info["voice"]
            tg_file = await bot.get_file(voice.file_id)
            file_path = tg_file.file_path
            if not file_path:
                raise Exception("File path is not available")

            file_path = _extract_file_path(file_path)
            token = bot.token
            local_file_path = Path(f"/data/{token}/{file_path}")

            with tempfile.TemporaryDirectory(prefix="multiply_voice_") as tmp_dir:
                tmp_dir_path = Path(tmp_dir)
                audio_path = tmp_dir_path / "voice.ogg"

                if not local_file_path.exists():
                    raise Exception(f"File not found: {file_path}")

                shutil.copy2(local_file_path, audio_path)

                output_path = tmp_dir_path / "multiplied.ogg"
                await asyncio.to_thread(
                    self._multiply_audio, audio_path, output_path, count
                )

                with output_path.open("rb") as final_file:
                    await get_message(update).chat.send_voice(
                        InputFile(final_file, filename="multiplied.ogg")
                    )

        except Exception as e:
            logger.exception("Error processing voice message: %s", e)
            await get_message(update).chat.send_message(
                "Ошибка при обработке голосового сообщения"
            )

    async def on_stop(self, update, session_context):
        await get_message(update).chat.send_message("Операция отменена")

    def help(self):
        return "/multiply - повторить голосовое сообщение n раз"

    def _multiply_audio(self, input_path: Path, output_path: Path, count: int):
        """Повторяет аудио count раз"""
        from moviepy.audio.AudioClip import concatenate_audioclips

        original_audio = AudioFileClip(str(input_path))

        try:
            audio_clips = [original_audio] * count
            final_audio = concatenate_audioclips(audio_clips)

            try:
                final_audio.write_audiofile(
                    str(output_path),
                    codec="libopus",
                    bitrate="64k",
                    ffmpeg_params=["-ar", "48000"],
                    logger=None,
                )
            finally:
                final_audio.close()
        finally:
            original_audio.close()
