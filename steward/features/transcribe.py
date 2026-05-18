import logging
from pathlib import Path
from typing import Any

from telegram import Message, ReactionTypeEmoji

from steward.features.voice_video.transcription import create_transcription_reply
from steward.framework import Feature, FeatureContext, step, subcommand, wizard
from steward.session.context import ChatStepContext
from steward.session.step import Step

logger = logging.getLogger(__name__)


_REPLY_HINT = (
    "Ответь этой командой на сообщение с голосовым, видеосообщением, "
    "видео или аудиофайлом."
)


def _resolve_file_id(obj: Any) -> tuple[str, bool] | None:
    """(file_id, is_video_note) для медиа из Message или ExternalReplyInfo.
    Возвращает None если нет ничего пригодного для расшифровки."""
    if obj is None:
        return None
    voice = getattr(obj, "voice", None)
    if voice:
        return voice.file_id, False
    video_note = getattr(obj, "video_note", None)
    if video_note:
        return video_note.file_id, True
    video = getattr(obj, "video", None)
    if video:
        return video.file_id, False
    audio = getattr(obj, "audio", None)
    if audio:
        return audio.file_id, False
    document = getattr(obj, "document", None)
    if document and (document.mime_type or "").startswith(("audio/", "video/")):
        return document.file_id, False
    return None


def _pick_source(message: Message) -> tuple[tuple[str, bool], Any] | None:
    """Ищем медиа: на самом сообщении → reply → external_reply (форвард-цитата
    из другого чата). Возвращает ((file_id, is_video_note), source_obj) или None."""
    candidates = (
        message,
        getattr(message, "reply_to_message", None),
        getattr(message, "external_reply", None),
    )
    for candidate in candidates:
        resolved = _resolve_file_id(candidate)
        if resolved is not None:
            return resolved, candidate
    return None


class _AwaitMediaStep(Step):
    """Сессия: ждём от юзера голосовое/видео/аудио. Промпт-сообщение бота
    запоминаем, чтобы удалить когда медиа придёт."""

    PROMPT = (
        "Слушаю. Пришли голосовое, видеосообщение, видео или аудиофайл — "
        "или /stop чтобы отменить."
    )
    NOT_MEDIA = (
        "Это не голосовое / видео / аудио. Пришли медиа или /stop."
    )

    def __init__(self) -> None:
        self.is_waiting = False

    async def chat(self, context: ChatStepContext) -> bool:
        message = context.message
        if message is None:
            return False
        if not self.is_waiting:
            prompt = await message.reply_text(self.PROMPT)
            if prompt is not None:
                context.session_context["_prompt_chat_id"] = prompt.chat_id
                context.session_context["_prompt_message_id"] = prompt.message_id
            self.is_waiting = True
            return False

        resolved = _resolve_file_id(message)
        if resolved is None:
            await message.reply_text(self.NOT_MEDIA)
            return False

        file_id, is_video_note = resolved
        context.session_context["file_id"] = file_id
        context.session_context["is_video_note"] = is_video_note
        from_user = message.from_user
        context.session_context["speaker_user_id"] = from_user.id if from_user else None
        context.session_context["speaker_username"] = from_user.username if from_user else None
        context.session_context["speaker_first_name"] = from_user.first_name if from_user else None
        context.session_context["media_chat_id"] = message.chat_id
        context.session_context["media_message_id"] = message.message_id
        return True

    def stop(self) -> None:
        self.is_waiting = False


class TranscribeFeature(Feature):
    command = "transcribe"
    description = "Расшифровка аудио/видео (ответом на сообщение или сессией)"
    help_examples = [
        "/transcribe ответом на голосовое — расшифровать его",
        "/transcribe — открыть сессию и потом прислать голос",
    ]

    @subcommand("", description="Сессия ожидания медиа, либо reply / attach")
    async def run(self, ctx: FeatureContext):
        message = ctx.message
        if message is None:
            return

        picked = _pick_source(message)
        if picked is not None:
            (file_id, is_video_note), source = picked
            await self._transcribe(
                ctx,
                file_id=file_id,
                is_video_note=is_video_note,
                source_message=source if isinstance(source, Message) else message,
            )
            return

        if getattr(message, "reply_to_message", None) is not None:
            # явный reply на не-медиа — кидаем хинт
            await ctx.reply(_REPLY_HINT, markdown=False)
            return

        # одиночный /transcribe — стартуем сессию
        await self.start_wizard("transcribe:wait_media", ctx)

    @wizard("transcribe:wait_media", step("media", _AwaitMediaStep()))
    async def on_session_done(
        self,
        ctx: FeatureContext,
        file_id: str | None = None,
        is_video_note: bool = False,
        speaker_user_id: int | None = None,
        speaker_username: str | None = None,
        speaker_first_name: str | None = None,
        media_chat_id: int | None = None,
        media_message_id: int | None = None,
        _prompt_chat_id: int | None = None,
        _prompt_message_id: int | None = None,
        **_,
    ):
        if _prompt_chat_id and _prompt_message_id:
            try:
                await self.bot.delete_message(
                    chat_id=_prompt_chat_id, message_id=_prompt_message_id
                )
            except Exception as e:
                logger.debug("transcribe prompt delete failed: %s", e)

        if not file_id:
            return

        source_message = ctx.message
        try:
            audio_path = await self._resolve_audio_path(ctx, file_id)
        except Exception as e:
            logger.warning("/transcribe session: file path resolution failed: %s", e)
            await ctx.reply("Не получилось забрать файл, попробуй ещё раз", markdown=False)
            return

        try:
            await create_transcription_reply(
                self.repository,
                source_message,
                audio_path,
                speaker_user_id,
                speaker_username,
                None,
                speaker_first_name,
                video_path=audio_path if is_video_note else None,
            )
        except Exception as e:
            logger.exception("/transcribe session: failed: %s", e)
            await ctx.reply("Не удалось сделать расшифровку", markdown=False)

    async def _transcribe(
        self,
        ctx: FeatureContext,
        *,
        file_id: str,
        is_video_note: bool,
        source_message: Message,
    ):
        try:
            audio_path = await self._resolve_audio_path(ctx, file_id)
        except Exception as e:
            logger.warning("/transcribe: file path resolution failed: %s", e)
            await ctx.reply("Не получилось забрать файл, попробуй ещё раз", markdown=False)
            return

        sender = source_message.from_user
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

    # Не показываем 🤷-реакцию больше — теперь /transcribe в одиночку = сессия.
