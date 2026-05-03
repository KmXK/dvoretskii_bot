import asyncio
import logging
import tempfile
from pathlib import Path

from moviepy.audio.io.AudioFileClip import AudioFileClip
from telegram import InputFile

from steward.framework import Feature, FeatureContext, ask, ask_message, subcommand, wizard
from steward.helpers.media import fetch_tg_file_to
from steward.helpers.tg_update_helpers import get_message
from steward.helpers.validation import (
    Error,
    try_get,
    validate_message_text,
)

logger = logging.getLogger(__name__)

_MAX_VOICE_DURATION = 600


def _audio_duration(path: Path) -> float:
    with AudioFileClip(str(path)) as clip:
        return clip.duration


def _multiply_audio(input_path: Path, output_path: Path, count: int):
    from moviepy.audio.AudioClip import concatenate_audioclips

    original = AudioFileClip(str(input_path))
    try:
        clips = [original] * count
        final = concatenate_audioclips(clips)
        try:
            final.write_audiofile(
                str(output_path),
                codec="libopus",
                bitrate="64k",
                ffmpeg_params=["-ar", "48000"],
                logger=None,
            )
        finally:
            final.close()
    finally:
        original.close()


class MultiplyFeature(Feature):
    command = "multiply"
    description = "Повторить голосовое сообщение N раз"

    @subcommand("", description="Запустить")
    async def start(self, ctx: FeatureContext):
        await self.start_wizard("multiply:start", ctx)

    @wizard(
        "multiply:start",
        ask_message(
            "voice_info",
            "Отправьте мне голосовое сообщение, которое нужно повторить",
            filter=lambda m: m.voice is not None,
            error="Это не голосовое сообщение. Пожалуйста, отправьте голосовое сообщение.",
            transform=lambda m: {"voice": m.voice},
        ),
        ask(
            "count",
            lambda state: (
                f"Сколько раз повторить голосовое сообщение? "
                f"(например, 3)"
            ),
            validator=validate_message_text([
                try_get(int, "Неверный формат. Пожалуйста, введите целое число (например, 3)"),
            ]),
        ),
    )
    async def on_done(
        self,
        ctx: FeatureContext,
        voice_info: dict,
        count: int,
    ):
        message = get_message(ctx.update)
        if count < 1:
            await message.chat.send_message("Количество повторений должно быть больше 0")
            return
        voice = voice_info["voice"]
        try:
            with tempfile.TemporaryDirectory(prefix="multiply_voice_") as tmp_dir:
                audio_path = Path(tmp_dir) / "voice.ogg"
                await fetch_tg_file_to(self.bot, voice.file_id, audio_path)
                duration = await asyncio.to_thread(_audio_duration, audio_path)
                max_count = int(_MAX_VOICE_DURATION / duration) if duration > 0 else 0
                if max_count < 1:
                    await message.chat.send_message(
                        f"Голосовое сообщение слишком длинное (больше {_MAX_VOICE_DURATION // 60} минут)."
                    )
                    return
                if count > max_count:
                    await message.chat.send_message(
                        f"Слишком много повторений. Максимум {max_count} раз."
                    )
                    return
                output_path = Path(tmp_dir) / "multiplied.ogg"
                await asyncio.to_thread(_multiply_audio, audio_path, output_path, count)
                with output_path.open("rb") as f:
                    await message.chat.send_voice(
                        InputFile(f, filename="multiplied.ogg")
                    )
        except Exception as e:
            logger.exception("Error processing voice message: %s", e)
            await message.chat.send_message("Ошибка при обработке голосового сообщения")
