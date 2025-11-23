import asyncio
import logging
import tempfile
from pathlib import Path

import aiohttp
from moviepy.audio.io.AudioFileClip import AudioFileClip
from telegram import InputFile

from steward.helpers.command_validation import validate_command_msg
from steward.helpers.tg_update_helpers import get_message
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step

logger = logging.getLogger(__name__)

# Максимальная длительность голосового сообщения в секундах (10 минут)
MAX_VOICE_DURATION = 600


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

        # Проверяем, что сообщение содержит голосовое сообщение
        if not context.message.voice:
            await context.message.reply_text(
                "Это не голосовое сообщение. Пожалуйста, отправьте голосовое сообщение."
            )
            return False

        # Получаем голосовое сообщение и его длительность
        voice = context.message.voice
        try:
            # Скачиваем временно для получения длительности
            # Используем context.bot.get_file() вместо voice.get_file()
            # так как в контексте сессии voice.get_file() может не работать
            tg_file = await context.bot.get_file(voice.file_id)
            with tempfile.TemporaryDirectory(prefix="multiply_voice_temp_") as tmp_dir:
                tmp_dir_path = Path(tmp_dir)
                audio_path = tmp_dir_path / "voice.ogg"

                # Скачиваем файл по URL через HTTP
                # Используем file_path для построения URL
                file_url = tg_file.file_path
                if file_url:
                    # Если file_path относительный, строим полный URL
                    if not file_url.startswith("http"):
                        file_url = f"https://api.telegram.org/file/bot{context.bot.token}/{file_url}"

                    async with aiohttp.ClientSession() as session:
                        async with session.get(file_url) as response:
                            with open(audio_path, "wb") as f:
                                async for chunk in response.content.iter_chunked(8192):
                                    f.write(chunk)
                else:
                    # Если URL недоступен, используем download_to_drive
                    await tg_file.download_to_drive(custom_path=str(audio_path))

                # Получаем длительность аудио
                audio_duration = await asyncio.to_thread(
                    self._get_audio_duration, audio_path
                )

                # Сохраняем информацию о голосовом сообщении и боте
                context.session_context[self.name] = {
                    "voice": voice,
                    "duration": audio_duration,
                }
                # Сохраняем бота для использования в on_session_finished
                context.session_context["bot"] = context.bot

        except Exception as e:
            logger.exception("Error getting voice duration: %s", e)
            await context.message.reply_text(
                f"Ошибка при обработке голосового сообщения: {str(e)}"
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
            # Получаем длительность голосового сообщения
            voice_info = context.session_context.get("voice_info", {})
            self.voice_duration = voice_info.get("duration")

            if self.voice_duration is None:
                await context.message.reply_text(
                    "Ошибка: не удалось определить длительность голосового сообщения"
                )
                return True  # Пропускаем этот шаг

            # Вычисляем максимальное количество повторений
            max_count = int(MAX_VOICE_DURATION / self.voice_duration)
            if max_count < 1:
                await context.message.reply_text(
                    f"Голосовое сообщение слишком длинное (больше {MAX_VOICE_DURATION // 60} минут). "
                    "Не могу создать повторение."
                )
                return True  # Пропускаем этот шаг

            await context.message.reply_text(
                f"Сколько раз повторить голосовое сообщение? "
                f"(максимум {max_count} раз, чтобы не превысить {MAX_VOICE_DURATION // 60} минут)"
            )
            self.is_waiting = True
            return False

        # Парсим количество
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

            # Проверяем максимальное количество повторений
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
        # Активируем сессию только если команда /multiply без дополнительных аргументов
        if not validate_command_msg(update, "multiply"):
            return False

        # Проверяем, что нет подкоманд
        assert update.message and update.message.text
        parts = update.message.text.split()
        if len(parts) > 1:
            return False  # Не обрабатываем аргументы

        return True

    async def on_session_finished(self, update, session_context):
        voice_info = session_context.get("voice_info", {})
        count = session_context.get("count")

        if not voice_info.get("voice") or count is None:
            await get_message(update).chat.send_message(
                "Ошибка: не удалось получить необходимые данные"
            )
            return

        # Получаем file_id из сохраненного voice объекта
        voice_file_id = voice_info["voice"].file_id
        bot = session_context.get("bot")

        if bot is None:
            await get_message(update).chat.send_message(
                "Ошибка: не удалось получить бота"
            )
            return

        try:
            # Получаем файл через бота, как в voice_video_handler
            # Используем сохраненный бот из контекста сессии
            tg_file = await bot.get_file(voice_file_id)
            with tempfile.TemporaryDirectory(prefix="multiply_voice_") as tmp_dir:
                tmp_dir_path = Path(tmp_dir)
                audio_path = tmp_dir_path / "voice.ogg"

                # Скачиваем файл по URL через HTTP
                # Используем file_path для построения URL
                file_url = tg_file.file_path
                if file_url:
                    # Если file_path относительный, строим полный URL
                    if not file_url.startswith("http"):
                        file_url = (
                            f"https://api.telegram.org/file/bot{bot.token}/{file_url}"
                        )

                    async with aiohttp.ClientSession() as session:
                        async with session.get(file_url) as response:
                            with open(audio_path, "wb") as f:
                                async for chunk in response.content.iter_chunked(8192):
                                    f.write(chunk)
                else:
                    # Если URL недоступен, используем download_to_drive
                    await tg_file.download_to_drive(custom_path=str(audio_path))

                # Создаем повторенное аудио
                output_path = tmp_dir_path / "multiplied.ogg"
                await asyncio.to_thread(
                    self._multiply_audio, audio_path, output_path, count
                )

                # Отправляем результат
                with output_path.open("rb") as final_file:
                    await get_message(update).chat.send_voice(
                        InputFile(final_file, filename="multiplied.ogg")
                    )

        except Exception as e:
            logger.exception("Error processing voice message: %s", e)
            await get_message(update).chat.send_message(
                f"Ошибка при обработке голосового сообщения: {str(e)}"
            )

    async def on_stop(self, update, session_context):
        await get_message(update).chat.send_message("Операция отменена")

    def help(self):
        return "/multiply - повторить голосовое сообщение n раз"

    def _multiply_audio(self, input_path: Path, output_path: Path, count: int):
        """Повторяет аудио count раз"""
        from moviepy.audio.AudioClip import concatenate_audioclips

        # Загружаем оригинальное аудио один раз
        original_audio = AudioFileClip(str(input_path))

        try:
            # Создаем список с одним и тем же клипом count раз
            # concatenate_audioclips правильно обработает это
            audio_clips = [original_audio] * count

            # Объединяем все копии
            final_audio = concatenate_audioclips(audio_clips)

            try:
                # Сохраняем результат в формате ogg
                # Используем ffmpeg для конвертации в ogg/opus
                # Указываем -ar 48000 в ffmpeg_params для конвертации sample rate
                # libopus поддерживает только 48000, 24000, 16000, 12000, 8000
                final_audio.write_audiofile(
                    str(output_path),
                    codec="libopus",
                    bitrate="64k",
                    ffmpeg_params=["-ar", "48000"],  # Устанавливаем sample rate 48000
                    logger=None,
                )
            finally:
                final_audio.close()
        finally:
            original_audio.close()
