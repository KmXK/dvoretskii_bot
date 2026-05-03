import asyncio
import html
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

from steward.data.models.ai_message import AiMessage
from steward.features.voice_video.conversion import run_ffmpeg
from steward.features.voice_video.visual import describe_video
from steward.helpers.ai import Model, make_text_stream
from steward.helpers.formats import spoiler_block
from steward.helpers.stt import transcribe_audio_bytes

logger = logging.getLogger(__name__)

_TG_TEXT_LIMIT = 4096
_SUMMARY_MIN_EDIT_INTERVAL = 1.2
_TRANSCRIPTION_BODY_LIMIT = 3500

_SUMMARY_SYSTEM_PROMPT = (
    "Ты делаешь ОЧЕНЬ краткую выжимку голосового сообщения. "
    "Максимум 1-3 коротких предложения, только суть, без воды, "
    "без вступлений вроде «в сообщении говорится», без приветствий "
    "и без перечисления очевидного. Сохрани тон и смысл. "
    "Если сообщение бессмысленное или это флуд — одно предложение "
    "о чём оно. Без кавычек и без форматирования."
)

_SUMMARY_SPEAKER_HINT = (
    "Говорящего зовут {name}. Используй это имя как СУБЪЕКТ действия "
    "в нужном падеже: «{name} говорит / спрашивает / называет кого-то X / "
    "жалуется / просит». Не ставь его в пассив как объект — он тот, кто "
    "произносит речь, а не тот, к кому обращаются. Местоимения «ты», "
    "«тебя», «тебе» в речи говорящего относятся к его собеседнику, а не "
    "к нему самому."
)

_SUMMARY_VISUAL_HINT = (
    "В кружке также есть видео. Вот краткое описание того, что в нём видно: "
    "«{visual}». Если визуал добавляет важную информацию (обстановка, действия, "
    "что показывают), коротко отрази это в выжимке; если визуал не несёт смысла "
    "сверх слов — игнорируй его."
)


def natural_speaker_name(
    repository,
    user_id: int | None,
    first_name: str | None,
    fallback_name: str | None,
) -> str | None:
    user = (
        next((u for u in repository.db.users if u.id == user_id), None)
        if user_id is not None
        else None
    )
    if user and user.stand_name:
        clean = user.stand_name.strip()
        if clean:
            return clean
    if first_name:
        clean = first_name.strip()
        if clean:
            return clean
    if fallback_name:
        clean = fallback_name.strip()
        if clean:
            return clean
    return None


def build_speaker_name(
    repository,
    user_id: int | None,
    fallback_username: str | None,
    fallback_name: str | None,
) -> str:
    user = (
        next((u for u in repository.db.users if u.id == user_id), None)
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


async def transcribe_voice(
    audio_path: Path,
    speaker_name: str | None = None,
    with_speaker_labels: bool = True,
) -> str | None:
    try:
        with tempfile.TemporaryDirectory(prefix="voice_stt_") as tmp_dir:
            prepared_audio = Path(tmp_dir) / "voice.mp3"
            await run_ffmpeg(
                "-i", str(audio_path),
                "-ac", "1",
                "-ar", "44100",
                str(prepared_audio),
            )
            return await transcribe_audio_bytes(
                prepared_audio.read_bytes(),
                with_speaker_labels=with_speaker_labels,
                primary_speaker_name=speaker_name,
            )
    except Exception as e:
        logger.exception("Voice transcription failed: %s", e)
        return None


async def _summary_stream(
    transcription: str,
    speaker_display_name: str | None,
    visual_context: str | None = None,
) -> AsyncIterator[str]:
    system_prompt = _SUMMARY_SYSTEM_PROMPT
    if speaker_display_name:
        system_prompt = (
            system_prompt + " " + _SUMMARY_SPEAKER_HINT.format(name=speaker_display_name)
        )
    if visual_context:
        system_prompt = (
            system_prompt + " " + _SUMMARY_VISUAL_HINT.format(visual=visual_context)
        )
    return await make_text_stream(
        0,
        Model.FAST,
        [("user", transcription)],
        system_prompt,
    )


def _compose_message(summary: str, spoiler_html: str) -> str:
    if summary:
        body = f"{html.escape(summary)}\n\n{spoiler_html}"
    else:
        body = spoiler_html
    if len(body) > _TG_TEXT_LIMIT:
        body = body[:_TG_TEXT_LIMIT]
    return body


async def _stream_summary_with_spoiler(
    reply_target,
    stream: AsyncIterator[str],
    spoiler_html: str,
    edit_message=None,
    reply_markup_provider: Callable[[], Any] | None = None,
):
    def current_markup():
        return reply_markup_provider() if reply_markup_provider is not None else None

    initial = f"<i>Коротко…</i>\n\n{spoiler_html}"
    if edit_message is not None:
        try:
            await edit_message.edit_text(
                initial,
                parse_mode=ParseMode.HTML,
                reply_markup=current_markup(),
            )
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                logger.warning("summary initial edit failed: %s", e)
        bot_message = edit_message
    else:
        bot_message = await reply_target.reply_html(initial)

    buffer: list[str] = []
    last_edit_at = 0.0
    last_text = initial
    got_anything = False

    try:
        async for chunk in stream:
            if not chunk:
                continue
            buffer.append(chunk)
            got_anything = True
            now = time.monotonic()
            if now - last_edit_at < _SUMMARY_MIN_EDIT_INTERVAL:
                continue
            text = _compose_message("".join(buffer), spoiler_html)
            if text == last_text:
                continue
            try:
                await bot_message.edit_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=current_markup(),
                )
                last_edit_at = now
                last_text = text
            except RetryAfter as e:
                await asyncio.sleep(float(e.retry_after))
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    logger.warning("summary stream edit failed: %s", e)
    except Exception as e:
        logger.exception("summary stream iteration failed: %s", e)

    summary = "".join(buffer).strip()
    final_text = _compose_message(summary if got_anything else "", spoiler_html)
    if final_text == last_text:
        return bot_message
    try:
        await bot_message.edit_text(
            final_text,
            parse_mode=ParseMode.HTML,
            reply_markup=current_markup(),
        )
    except RetryAfter as e:
        await asyncio.sleep(float(e.retry_after))
        try:
            await bot_message.edit_text(
                final_text,
                parse_mode=ParseMode.HTML,
                reply_markup=current_markup(),
            )
        except BadRequest as e2:
            logger.warning("summary final edit failed: %s", e2)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("summary final edit failed: %s", e)
    return bot_message


async def create_transcription_reply(
    repository,
    reply_target,
    audio_path: Path,
    speaker_user_id: int | None,
    speaker_username: str | None,
    speaker_fallback_name: str | None,
    speaker_first_name: str | None = None,
    video_path: Path | None = None,
    edit_message=None,
    reply_markup_provider: Callable[[], Any] | None = None,
):
    speaker_name = build_speaker_name(
        repository,
        speaker_user_id,
        speaker_username,
        speaker_fallback_name,
    )
    natural_name = natural_speaker_name(
        repository,
        speaker_user_id,
        speaker_first_name,
        speaker_fallback_name,
    )

    voice_task = asyncio.create_task(transcribe_voice(audio_path, speaker_name))
    visual_task = (
        asyncio.create_task(describe_video(video_path)) if video_path is not None else None
    )

    transcription = await voice_task
    if not transcription:
        if visual_task is not None:
            visual_task.cancel()
        error_text = "Не удалось сделать расшифровку"
        if edit_message is not None:
            markup = reply_markup_provider() if reply_markup_provider else None
            try:
                await edit_message.edit_text(error_text, reply_markup=markup)
                return
            except Exception as e:
                logger.warning("failed to edit message with transcription error: %s", e)
        await reply_target.reply_text(error_text)
        return

    visual_description: str | None = None
    if visual_task is not None:
        try:
            visual_description = await visual_task
        except asyncio.CancelledError:
            visual_description = None
        except Exception as e:
            logger.exception("visual description task failed: %s", e)
            visual_description = None

    body = (
        transcription
        if len(transcription) <= _TRANSCRIPTION_BODY_LIMIT
        else transcription[:_TRANSCRIPTION_BODY_LIMIT] + "..."
    )
    transcription_spoiler = spoiler_block(body)
    spoiler_html = transcription_spoiler
    if visual_description:
        spoiler_html = transcription_spoiler + "\n" + spoiler_block(
            visual_description, header="🎬 Визуал"
        )

    try:
        stream = await _summary_stream(transcription, natural_name, visual_description)
    except Exception as e:
        logger.exception("summary stream init failed: %s", e)
        if edit_message is not None:
            markup = reply_markup_provider() if reply_markup_provider else None
            try:
                await edit_message.edit_text(
                    spoiler_html,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                bot_message = edit_message
            except Exception as edit_err:
                logger.warning("failed to edit message with spoiler: %s", edit_err)
                bot_message = await reply_target.reply_html(spoiler_html)
        else:
            bot_message = await reply_target.reply_html(spoiler_html)
    else:
        bot_message = await _stream_summary_with_spoiler(
            reply_target,
            stream,
            spoiler_html,
            edit_message=edit_message,
            reply_markup_provider=reply_markup_provider,
        )

    if bot_message is not None:
        await _register_ai_reply_target(repository, reply_target, bot_message)


async def _register_ai_reply_target(repository, reply_target, bot_message) -> None:
    try:
        chat_id = reply_target.chat.id
        msg_id = bot_message.message_id
        repository.db.ai_messages[f"{chat_id}_{msg_id}"] = AiMessage(
            time.time(), reply_target.message_id, "ai"
        )
        if len(repository.db.ai_messages) > 1000:
            oldest = min(
                repository.db.ai_messages,
                key=lambda k: repository.db.ai_messages[k].timestamp,
            )
            del repository.db.ai_messages[oldest]
        await repository.save()
    except Exception as e:
        logger.debug("failed to register transcription as ai reply target: %s", e)
