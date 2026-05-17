import logging
from pathlib import Path

from telegram import Message, ReactionTypeEmoji

from steward.features.voice_video.transcription import create_transcription_reply
from steward.framework import Feature, FeatureContext, subcommand

logger = logging.getLogger(__name__)


_REPLY_HINT = (
    "Ответь этой командой на сообщение с голосовым, видеосообщением, "
    "видео или аудиофайлом."
)


def _resolve_file_id(message: Message | None) -> tuple[str, bool] | None:
    """Возвращает (file_id, is_video_note) для медиа, поддерживаемого расшифровкой."""
    if message is None:
        return None
    if message.voice:
        return message.voice.file_id, False
    if message.video_note:
        return message.video_note.file_id, True
    if message.video:
        return message.video.file_id, False
    if message.audio:
        return message.audio.file_id, False
    if message.document and (message.document.mime_type or "").startswith(("audio/", "video/")):
        return message.document.file_id, False
    return None


class TranscribeFeature(Feature):
    command = "transcribe"
    description = "Расшифровка аудио/видео (ответом на сообщение)"
    help_examples = [
        "/transcribe — ответом на голосовое/видео/аудио сообщение",
    ]

    @subcommand("", description="Ответом на сообщение с аудио/видео")
    async def run(self, ctx: FeatureContext):
        message = ctx.message
        if message is None:
            return
        reply = message.reply_to_message

        source_message = None
        resolved = _resolve_file_id(message)
        if resolved is not None:
            source_message = message
        else:
            resolved = _resolve_file_id(reply)
            if resolved is not None:
                source_message = reply

        if resolved is None:
            # reply на текст — явная ошибка, кидаем хинт. Без reply — скорее
            # всего юзер пришлёт форвард голосового рядом, авто-расшифровка
            # сама отработает. Шуметь хинтом не нужно — тихо реагируем 🤷.
            if reply is not None:
                await ctx.reply(_REPLY_HINT, markdown=False)
                return
            try:
                await ctx.bot.set_message_reaction(
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    reaction=[ReactionTypeEmoji(emoji="🤷")],
                )
            except Exception as e:
                logger.debug("/transcribe silent react failed: %s", e)
            return

        file_id, is_video_note = resolved
        sender = source_message.from_user
        try:
            audio_path = await self._resolve_audio_path(ctx, file_id)
        except Exception as e:
            logger.warning("/transcribe: file path resolution failed: %s", e)
            await ctx.reply("Не получилось забрать файл, попробуй ещё раз", markdown=False)
            return

        placeholder = await ctx.reply("Слушаю…", markdown=False)
        try:
            await create_transcription_reply(
                self.repository,
                source_message,
                audio_path,
                sender.id if sender else None,
                sender.username if sender else None,
                None,
                sender.first_name if sender else None,
                video_path=audio_path if is_video_note else None,
                edit_message=placeholder,
            )
        except Exception as e:
            logger.exception("/transcribe failed: %s", e)
            try:
                await placeholder.edit_text("Не удалось сделать расшифровку")
            except Exception:
                pass

    async def _resolve_audio_path(self, ctx: FeatureContext, file_id: str) -> Path:
        tg_file = await ctx.bot.get_file(file_id)
        if not tg_file.file_path:
            raise Exception("File path is not available")
        fp = tg_file.file_path
        if "/file/bot" in fp:
            fp = fp.split("/file/bot", 1)[1].split("/", 1)[1]
        audio_path = Path(f"/data/{ctx.bot.token}/{fp}")
        if not audio_path.exists():
            raise Exception(f"File not found: {audio_path}")
        return audio_path
