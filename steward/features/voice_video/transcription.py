import asyncio
import html
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, cast

import httpx
from elevenlabs.client import ElevenLabs
from elevenlabs.types import SpeechToTextChunkResponseModel
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

from steward.features.voice_video.conversion import run_ffmpeg
from steward.helpers.ai import OpenRouterModel, make_openrouter_stream
from steward.helpers.formats import spoiler_block
from steward.helpers.transcription import build_named_speakers_text

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
    "Говорящего зовут {name}. В выжимке используй это имя "
    "(в нужном падеже) вместо обобщений «автор», «спикер», "
    "«человек»."
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
    stt_key = os.environ.get("EVELEN_LABS_STT")
    if not stt_key:
        logger.warning("Voice transcription skipped: EVELEN_LABS_STT is not set")
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="voice_stt_") as tmp_dir:
            prepared_audio = Path(tmp_dir) / "voice.mp3"
            await run_ffmpeg(
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


async def _summary_stream(
    transcription: str, speaker_display_name: str | None
) -> AsyncIterator[str]:
    system_prompt = _SUMMARY_SYSTEM_PROMPT
    if speaker_display_name:
        system_prompt = (
            system_prompt + " " + _SUMMARY_SPEAKER_HINT.format(name=speaker_display_name)
        )
    return await make_openrouter_stream(
        0,
        OpenRouterModel.FAST,
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
):
    initial = f"<i>Коротко…</i>\n\n{spoiler_html}"
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
                await bot_message.edit_text(text, parse_mode=ParseMode.HTML)
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
        await bot_message.edit_text(final_text, parse_mode=ParseMode.HTML)
    except RetryAfter as e:
        await asyncio.sleep(float(e.retry_after))
        try:
            await bot_message.edit_text(final_text, parse_mode=ParseMode.HTML)
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
    transcription = await transcribe_voice(audio_path, speaker_name)
    if not transcription:
        await reply_target.reply_text("Не удалось сделать расшифровку")
        return

    body = (
        transcription
        if len(transcription) <= _TRANSCRIPTION_BODY_LIMIT
        else transcription[:_TRANSCRIPTION_BODY_LIMIT] + "..."
    )
    spoiler = spoiler_block(body)

    try:
        stream = await _summary_stream(transcription, natural_name)
    except Exception as e:
        logger.exception("summary stream init failed: %s", e)
        await reply_target.reply_html(spoiler)
        return

    await _stream_summary_with_spoiler(reply_target, stream, spoiler)
