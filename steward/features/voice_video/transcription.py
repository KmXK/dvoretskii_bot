import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import cast

import httpx
from elevenlabs.client import ElevenLabs
from elevenlabs.types import SpeechToTextChunkResponseModel

from steward.features.voice_video.conversion import run_ffmpeg
from steward.helpers.transcription import build_named_speakers_text

logger = logging.getLogger(__name__)


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


async def create_transcription_reply(
    repository,
    reply_target,
    audio_path: Path,
    speaker_user_id: int | None,
    speaker_username: str | None,
    speaker_fallback_name: str | None,
):
    speaker_name = build_speaker_name(
        repository,
        speaker_user_id,
        speaker_username,
        speaker_fallback_name,
    )
    transcription = await transcribe_voice(audio_path, speaker_name)
    if not transcription:
        await reply_target.reply_text("Не удалось сделать расшифровку")
        return
    if len(transcription) > 3900:
        transcription = transcription[:3900] + "..."
    await reply_target.reply_text(f"Расшифровка:\n{transcription}")
