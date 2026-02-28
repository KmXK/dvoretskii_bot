import asyncio
import dataclasses
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import cast
import uuid

import httpx
from elevenlabs.client import ElevenLabs
from elevenlabs.types import SpeechToTextChunkResponseModel
from pyrate_limiter import BucketFullException
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from steward.bot.context import ChatBotContext
from steward.handlers.handler import Handler
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.transcription import build_named_speakers_text

logger = logging.getLogger(__name__)

VIDEO_PATH = Path("data/videos/stupid_video.mp4")
BG_AUDIO_PATH = Path("data/audio/lofi.mp3")
VOICE_DAILY_LIMIT_SECONDS = 10 * 60

VIDEO_VARIANTS = [
    (1600.0, Path("data/videos/stupid_video_240p.mp4")),
    (360.0, Path("data/videos/stupid_video_480p.mp4")),
    (0.0, Path("data/videos/stupid_video_720p.mp4")),
]


@dataclasses.dataclass
class _PendingVoiceRequest:
    file_id: str
    requester_user_id: int
    speaker_user_id: int | None
    speaker_username: str | None
    speaker_fallback_name: str | None
    video_clicked: bool = False
    transcribe_clicked: bool = False
    request_clicked: bool = False


def _pick_video(audio_dur: float) -> Path:
    for threshold, path in VIDEO_VARIANTS:
        if audio_dur >= threshold and path.exists():
            return path
    raise Exception(
        f"Invalid configuration: no video found for audio duration {audio_dur} seconds"
    )


async def _get_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return float(stdout.decode().strip())


async def _run_ffmpeg(*args: str):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"ffmpeg failed: {stderr.decode()}")


class VoiceVideoHandler(Handler):
    VIDEO_OFFSET_KEY = "stupid_video"
    BG_AUDIO_OFFSET_KEY = "lofi_audio"
    CALLBACK_PREFIX = "voice_video_handler"
    MAX_PENDING_REQUESTS = 200

    def __init__(self):
        self._pending: dict[str, _PendingVoiceRequest] = {}

    def _build_actions_keyboard(
        self, request_id: str, pending: _PendingVoiceRequest
    ) -> InlineKeyboardMarkup | None:
        row: list[InlineKeyboardButton] = []
        if not pending.video_clicked:
            row.append(
                InlineKeyboardButton(
                    "Видео",
                    callback_data=f"{self.CALLBACK_PREFIX}|video|{request_id}",
                )
            )
        if not pending.transcribe_clicked:
            row.append(
                InlineKeyboardButton(
                    "Расшифровка",
                    callback_data=f"{self.CALLBACK_PREFIX}|transcribe|{request_id}",
                )
            )
        if not pending.request_clicked:
            row.append(
                InlineKeyboardButton(
                    "Запрос",
                    callback_data=f"{self.CALLBACK_PREFIX}|request|{request_id}",
                )
            )
        if not row:
            return None
        return InlineKeyboardMarkup(
            [
                row,
                [
                    InlineKeyboardButton(
                        "Ничего",
                        callback_data=f"{self.CALLBACK_PREFIX}|nothing|{request_id}",
                    )
                ],
            ]
        )

    async def chat(self, context):
        if not context.message.voice:
            return False
        from_user = context.message.from_user
        if not from_user:
            return False

        request_id = uuid.uuid4().hex
        speaker_user_id = from_user.id
        speaker_username = from_user.username
        speaker_fallback_name = None
        origin = getattr(context.message, "forward_origin", None)
        if origin is not None:
            if hasattr(origin, "sender_user") and origin.sender_user:
                speaker_user = origin.sender_user
                speaker_user_id = speaker_user.id
                speaker_username = speaker_user.username
            elif hasattr(origin, "sender_user_name") and origin.sender_user_name:
                speaker_user_id = None
                speaker_username = None
                speaker_fallback_name = origin.sender_user_name

        self._pending[request_id] = _PendingVoiceRequest(
            file_id=context.message.voice.file_id,
            requester_user_id=from_user.id,
            speaker_user_id=speaker_user_id,
            speaker_username=speaker_username,
            speaker_fallback_name=speaker_fallback_name,
        )
        if len(self._pending) > self.MAX_PENDING_REQUESTS:
            self._pending.pop(next(iter(self._pending)))

        keyboard = self._build_actions_keyboard(request_id, self._pending[request_id])
        await context.message.reply_text(
            "Выбери действие для голосового сообщения:",
            reply_markup=keyboard,
        )
        return True

    async def callback(self, context):
        data = context.callback_query.data
        if not data:
            return False

        parts = data.split("|")
        if len(parts) != 3 or parts[0] != self.CALLBACK_PREFIX:
            return False

        action = parts[1]
        request_id = parts[2]
        pending = self._pending.get(request_id)
        if pending is None:
            await context.callback_query.answer("Запрос устарел")
            return True

        if action == "nothing":
            self._pending.pop(request_id, None)
            await context.callback_query.answer()
            try:
                await context.callback_query.message.delete()
            except Exception:
                await context.callback_query.message.edit_reply_markup(reply_markup=None)
            return True

        if action == "video":
            if pending.video_clicked:
                await context.callback_query.answer("Кнопка уже нажата")
                return True
            pending.video_clicked = True
        elif action == "transcribe":
            if pending.transcribe_clicked:
                await context.callback_query.answer("Кнопка уже нажата")
                return True
            pending.transcribe_clicked = True
        elif action == "request":
            if pending.request_clicked:
                await context.callback_query.answer("Кнопка уже нажата")
                return True
            pending.request_clicked = True
        else:
            await context.callback_query.answer("Неизвестное действие")
            return True

        await context.callback_query.answer()
        await context.callback_query.message.edit_reply_markup(
            reply_markup=self._build_actions_keyboard(request_id, pending)
        )

        try:
            audio_path = await self._resolve_audio_path(context, pending.file_id)
            if action == "video":
                await self._create_video_reply(
                    context,
                    audio_path,
                    pending.requester_user_id,
                )
            elif action == "transcribe":
                await self._create_transcription_reply(context, audio_path, pending)
            elif action == "request":
                await self._create_router_request(context, audio_path)
            if (
                pending.video_clicked
                and pending.transcribe_clicked
                and pending.request_clicked
            ):
                self._pending.pop(request_id, None)
            return True
        except Exception as e:
            logger.exception("Error processing voice callback: %s", e)
            await context.callback_query.message.reply_text(
                "Ошибка при обработке голосового сообщения"
            )
            return True

    async def _create_router_request(self, context, audio_path: Path):
        transcription = await self._transcribe_voice(
            audio_path,
            speaker_name=None,
            with_speaker_labels=False,
        )
        if not transcription:
            await context.callback_query.message.reply_text(
                "Не удалось распознать голос для запроса"
            )
            return

        request_text = f"дворецкий, {transcription.strip()}"
        router_message = _RouterMessageProxy(
            context.callback_query.message,
            context.callback_query.from_user,
            request_text,
        )
        chat_context = ChatBotContext(
            context.repository,
            context.bot,
            context.client,
            context.update,
            context.tg_context,
            context.metrics,
            router_message,
        )
        all_handlers = getattr(self, "_all_handlers", [])
        for handler in all_handlers:
            if handler.__class__.__name__ != "AiRouterHandler":
                continue
            handled = await handler.chat(chat_context)
            if not handled:
                await context.callback_query.message.reply_text(
                    "Не удалось обработать запрос из голосового"
                )
            return
        await context.callback_query.message.reply_text(
            "Роутер команд недоступен"
        )

    def _patch_text_as_butler_request(self, message):
        raw_text = (message.text or "").strip()
        if not raw_text:
            return
        if raw_text.lower().startswith("дворецкий") or raw_text.lower().startswith("уважаемый"):
            return
        patched_text = f"дворецкий, {raw_text}"
        was_frozen = getattr(message, "_frozen", False)
        if was_frozen:
            object.__setattr__(message, "_frozen", False)
        message.text = patched_text
        if was_frozen:
            object.__setattr__(message, "_frozen", True)

    async def _resolve_audio_path(self, context, file_id: str) -> Path:
        tg_file = await context.bot.get_file(file_id)
        if not tg_file.file_path:
            raise Exception("File path is not available")

        fp = tg_file.file_path
        if "/file/bot" in fp:
            fp = fp.split("/file/bot", 1)[1].split("/", 1)[1]
        audio_path = Path(f"/data/{context.bot.token}/{fp}")
        if not audio_path.exists():
            raise Exception(f"File not found: {audio_path}")
        return audio_path

    async def _create_video_reply(self, context, audio_path: Path, user_id: int):
        if not VIDEO_PATH.exists():
            logger.warning("VoiceVideoHandler skipped: %s not found", VIDEO_PATH)
            await context.callback_query.message.reply_text("Видео временно недоступно")
            return

        tasks = [_get_duration(audio_path), _get_duration(VIDEO_PATH)]
        has_bg = BG_AUDIO_PATH.exists()
        if has_bg:
            tasks.append(_get_duration(BG_AUDIO_PATH))

        durations = await asyncio.gather(*tasks)
        audio_dur, video_dur = durations[0], durations[1]
        bg_dur = durations[2] if has_bg else None

        needed = audio_dur + 1.0
        if needed >= video_dur:
            await context.callback_query.message.reply_text(
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
            await context.callback_query.message.reply_text(
                "Лимит на голосовые исчерпан: 10 минут в сутки на пользователя."
            )
            return

        video_path = _pick_video(audio_dur)
        video_start = self._pick_offset(self.VIDEO_OFFSET_KEY, needed, video_dur)
        bg_start = (
            self._pick_offset(self.BG_AUDIO_OFFSET_KEY, needed, bg_dur)
            if bg_dur
            else None
        )

        fd, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            await self._render(
                video_path, video_start, needed, audio_path, out_path, bg_start
            )
            self._update_offset(self.VIDEO_OFFSET_KEY, video_start + needed, video_dur)
            if bg_dur and bg_start is not None:
                self._update_offset(self.BG_AUDIO_OFFSET_KEY, bg_start + needed, bg_dur)
            await self.repository.save()

            with open(out_path, "rb") as f:
                await context.callback_query.message.reply_video(
                    InputFile(f, filename="reply.mp4")
                )
        finally:
            os.unlink(out_path)

    async def _create_transcription_reply(
        self, context, audio_path: Path, pending: _PendingVoiceRequest
    ):
        speaker_name = self._build_speaker_name(
            pending.speaker_user_id,
            pending.speaker_username,
            pending.speaker_fallback_name,
        )
        transcription = await self._transcribe_voice(audio_path, speaker_name)
        if not transcription:
            await context.callback_query.message.reply_text(
                "Не удалось сделать расшифровку"
            )
            return
        if len(transcription) > 3900:
            transcription = transcription[:3900] + "..."
        await context.callback_query.message.reply_text(
            f"Расшифровка:\n{transcription}"
        )

    def _pick_offset(self, key: str, needed: float, total: float) -> float:
        start = self.repository.db.data_offsets.get(key, 0.0)
        return 0.0 if start >= total or total - start < needed else start

    def _update_offset(self, key: str, val: float, total: float):
        self.repository.db.data_offsets[key] = val if val < total else 0.0

    async def _render(
        self,
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
                await _run_ffmpeg(
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
                await _run_ffmpeg(
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
            await _run_ffmpeg(
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

    def _build_speaker_name(
        self,
        user_id: int | None,
        fallback_username: str | None,
        fallback_name: str | None,
    ) -> str:
        user = (
            next((u for u in self.repository.db.users if u.id == user_id), None)
            if user_id is not None
            else None
        )
        username = (user.username if user else None) or fallback_username
        if user and user.stand_name:
            stand_name = user.stand_name.strip()
            if stand_name:
                return f"{stand_name} (@{username})" if username else stand_name
        if username:
            return f"@{username}"
        if fallback_name:
            return fallback_name
        if user_id is not None:
            return f"user_{user_id}"
        return "unknown"

    async def _transcribe_voice(
        self,
        audio_path: Path,
        speaker_name: str | None = None,
        with_speaker_labels: bool = True,
    ) -> str | None:
        stt_key = os.environ.get("EVELEN_LABS_STT")
        if not stt_key:
            logger.warning("Voice transcription skipped: EVELEN_LABS_STT is not set")
            return None

        try:
            with tempfile.TemporaryDirectory(prefix="voice_stt_") as tmp_dir:
                prepared_audio = Path(tmp_dir) / "voice.mp3"
                await _run_ffmpeg(
                    "-i",
                    str(audio_path),
                    "-ac",
                    "1",
                    "-ar",
                    "44100",
                    str(prepared_audio),
                )

                with open(prepared_audio, "rb") as audio_file:
                    client = ElevenLabs(
                        api_key=stt_key,
                        httpx_client=httpx.Client(
                            timeout=240,
                            proxy=os.environ.get("DOWNLOAD_PROXY"),
                        ),
                    )
                    result = await asyncio.to_thread(
                        lambda: client.speech_to_text.convert(
                            file=audio_file.read(),
                            model_id="scribe_v1",
                            tag_audio_events=True,
                            diarize=True,
                        )
                    )

                words = cast(SpeechToTextChunkResponseModel, result).words or []
                if with_speaker_labels and words:
                    text_with_names = build_named_speakers_text(
                        words, primary_speaker_name=speaker_name
                    )
                    if text_with_names:
                        return text_with_names

                text = getattr(result, "text", None)
                if isinstance(text, str):
                    clean_text = text.strip()
                    return clean_text if clean_text else None
        except Exception as e:
            logger.exception("Voice transcription failed: %s", e)

        return None


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
