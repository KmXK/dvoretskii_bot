import dataclasses
import logging
import uuid
from pathlib import Path

from steward.bot.context import ChatBotContext
from steward.features.voice_video.conversion import create_video_reply
from steward.features.voice_video.transcription import (
    create_transcription_reply,
    transcribe_voice,
)
from steward.framework import (
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    on_callback,
    on_message,
    subcommand,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _PendingVoiceRequest:
    file_id: str
    requester_user_id: int
    speaker_user_id: int | None
    speaker_username: str | None
    speaker_fallback_name: str | None
    speaker_first_name: str | None
    is_video_note: bool = False
    transcribe_clicked: bool = False
    request_clicked: bool = False


class _RouterMessageProxy:
    def __init__(self, base_message, from_user, text: str):
        self._base_message = base_message
        self.from_user = from_user
        self.text = text
        self.entities = ()
        self.reply_to_message = None
        self.chat = base_message.chat

    def __getattr__(self, name):
        return getattr(self._base_message, name)


class VoiceVideoFeature(Feature):
    command = "voice_to_video"
    description = "Сделать видео-ответ из голосового"
    excluded_from_ai_router = True

    VIDEO_OFFSET_KEY = "stupid_video"
    BG_AUDIO_OFFSET_KEY = "lofi_audio"
    MAX_PENDING_REQUESTS = 200

    def __init__(self):
        super().__init__()
        self._pending: dict[str, _PendingVoiceRequest] = {}

    def _build_actions_keyboard(
        self, request_id: str, pending: _PendingVoiceRequest
    ) -> Keyboard | None:
        cb = self.cb("voice:action")
        row: list[Button] = []
        if not pending.transcribe_clicked:
            row.append(cb.button("Расшифровка", action="transcribe", request_id=request_id))
        if not pending.request_clicked:
            row.append(cb.button("Запрос", action="request", request_id=request_id))
        if not row:
            return None
        rows: list[list[Button]] = [row]
        if not pending.transcribe_clicked:
            rows.append([cb.button("Ничего", action="nothing", request_id=request_id)])
        return Keyboard(rows)

    @subcommand("", description="Сделать видео-ответ (в ответ на голосовое)")
    async def voice_to_video_cmd(self, ctx: FeatureContext):
        message = ctx.message
        if message is None:
            return
        reply = message.reply_to_message
        if reply is None or not reply.voice:
            await ctx.reply(
                "Команда работает только как ответ на голосовое сообщение.",
                markdown=False,
            )
            return
        try:
            audio_path = await self._resolve_audio_path(ctx, reply.voice.file_id)
            await create_video_reply(
                self,
                reply,
                audio_path,
                ctx.user_id,
                self.VIDEO_OFFSET_KEY,
                self.BG_AUDIO_OFFSET_KEY,
            )
        except Exception as e:
            logger.exception("voice_to_video command failed: %s", e)
            await ctx.reply("Не удалось сделать видео", markdown=False)

    @on_message
    async def on_voice(self, ctx: FeatureContext) -> bool:
        message = ctx.message
        if message is None:
            return False
        if message.voice:
            file_id = message.voice.file_id
            is_video_note = False
        elif message.video_note:
            file_id = message.video_note.file_id
            is_video_note = True
        else:
            return False
        from_user = message.from_user
        if not from_user:
            return False

        request_id = uuid.uuid4().hex
        speaker_user_id: int | None = from_user.id
        speaker_username = from_user.username
        speaker_first_name: str | None = from_user.first_name
        speaker_fallback_name: str | None = None
        origin = getattr(message, "forward_origin", None)
        if origin is not None:
            if hasattr(origin, "sender_user") and origin.sender_user:
                speaker_user = origin.sender_user
                speaker_user_id = speaker_user.id
                speaker_username = speaker_user.username
                speaker_first_name = getattr(speaker_user, "first_name", None)
            elif hasattr(origin, "sender_user_name") and origin.sender_user_name:
                speaker_user_id = None
                speaker_username = None
                speaker_first_name = None
                speaker_fallback_name = origin.sender_user_name

        self._pending[request_id] = _PendingVoiceRequest(
            file_id=file_id,
            requester_user_id=from_user.id,
            speaker_user_id=speaker_user_id,
            speaker_username=speaker_username,
            speaker_fallback_name=speaker_fallback_name,
            speaker_first_name=speaker_first_name,
            is_video_note=is_video_note,
        )
        if len(self._pending) > self.MAX_PENDING_REQUESTS:
            self._pending.pop(next(iter(self._pending)))

        keyboard = self._build_actions_keyboard(request_id, self._pending[request_id])
        await ctx.reply(
            "Выбери действие для сообщения:",
            keyboard=keyboard,
            markdown=False,
        )
        return True

    @on_callback(
        "voice:action",
        schema="<action:literal[transcribe|request|nothing]>|<request_id:str>",
    )
    async def on_action(self, ctx: FeatureContext, action: str, request_id: str):
        callback_query = ctx.callback_query
        if callback_query is None:
            return
        message = callback_query.message
        pending = self._pending.get(request_id)
        if pending is None:
            await callback_query.answer("Запрос устарел")
            return

        if action == "nothing":
            await callback_query.answer()
            self._pending.pop(request_id, None)
            try:
                await message.delete()
            except Exception as e:
                logger.warning("Failed to delete voice action menu: %s", e)
                try:
                    await message.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass
            return

        if action == "transcribe":
            if pending.transcribe_clicked:
                await callback_query.answer("Кнопка уже нажата")
                return
            pending.transcribe_clicked = True
        elif action == "request":
            if pending.request_clicked:
                await callback_query.answer("Кнопка уже нажата")
                return
            pending.request_clicked = True

        await callback_query.answer()

        def reply_markup_provider():
            kb = self._build_actions_keyboard(request_id, pending)
            return kb.to_markup() if kb is not None else None

        try:
            await message.edit_reply_markup(reply_markup=reply_markup_provider())
        except Exception as e:
            logger.debug("keyboard update failed: %s", e)

        try:
            audio_path = await self._resolve_audio_path(ctx, pending.file_id)
            if action == "transcribe":
                initiator = message.reply_to_message or message
                await create_transcription_reply(
                    self.repository,
                    initiator,
                    audio_path,
                    pending.speaker_user_id,
                    pending.speaker_username,
                    pending.speaker_fallback_name,
                    pending.speaker_first_name,
                    video_path=audio_path if pending.is_video_note else None,
                    edit_message=message,
                    reply_markup_provider=reply_markup_provider,
                )
            elif action == "request":
                await self._create_router_request(ctx, audio_path)
            if pending.transcribe_clicked and pending.request_clicked:
                self._pending.pop(request_id, None)
        except Exception as e:
            logger.exception("Error processing voice callback: %s", e)
            await message.reply_text("Ошибка при обработке сообщения")

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

    async def _create_router_request(self, ctx: FeatureContext, audio_path: Path):
        callback_query = ctx.callback_query
        if callback_query is None or callback_query.message is None:
            return
        message = callback_query.message
        transcription = await transcribe_voice(
            audio_path,
            speaker_name=None,
            with_speaker_labels=False,
        )
        if not transcription:
            await message.reply_text("Не удалось распознать голос для запроса")
            return
        request_text = f"дворецкий, {transcription.strip()}"
        router_message = _RouterMessageProxy(
            message,
            callback_query.from_user,
            request_text,
        )
        chat_context = ChatBotContext(
            ctx.repository,
            ctx.bot,
            ctx.client,
            ctx.update,
            ctx.tg_context,
            ctx.metrics,
            router_message,
        )
        all_handlers = getattr(self, "_all_handlers", [])
        for handler in all_handlers:
            if handler.__class__.__name__ != "AiRouterHandler":
                continue
            handled = await handler.chat(chat_context)
            if not handled:
                await message.reply_text("Не удалось обработать запрос из голосового")
            return
        await message.reply_text("Роутер команд недоступен")
