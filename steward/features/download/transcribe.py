import asyncio
import logging
import os
import tempfile
from typing import cast

import httpx
import yt_dlp
from elevenlabs.client import ElevenLabs
from elevenlabs.types import SpeechToTextChunkResponseModel
from telegram import Message

from steward.data.repository import Repository
from steward.features.download.callbacks import download_file
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.transcription import build_named_speakers_text, wrap_as_spoiler

logger = logging.getLogger("download_controller")
yt_logger = logging.getLogger("youtube_dl")


async def make_transcribation(
    repository: Repository, message: Message, url: str
) -> bool:
    check_limit("TRANSCRIBATION_LIMIT", 5, Duration.MINUTE)
    check_limit(f"TRANSCRIBATION_LIMIT_{message.id}", 1, 10 * Duration.SECOND)

    real_uuid = url
    if url.startswith("no_ydl_"):
        real_uuid = url[len("no_ydl_") :]

    saved_url = repository.db.saved_links.get(real_uuid)
    if saved_url is None:
        logger.error("transcribation for saved link was not found")
        return True

    with tempfile.TemporaryDirectory(prefix="transcribation_") as dir:
        duration: float | None = None
        if url.startswith("no_ydl_"):
            async with download_file(saved_url, use_proxy=True) as file:
                output_path = os.path.join(dir, "out.mp3")

                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg",
                    "-y",
                    "-i",
                    file.name,
                    "-ac",
                    "1",
                    "-ar",
                    "44100",
                    output_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logging.error(
                        "ffmpeg failed to convert file: %s",
                        stderr.decode(errors="replace"),
                    )
                    return False

            ffprobe = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _err = await ffprobe.communicate()
            if ffprobe.returncode == 0:
                try:
                    duration = float(out.decode().strip())
                except Exception:
                    duration = None
        else:
            filepath = dir + "/file"
            info = await asyncio.to_thread(
                lambda: yt_dlp.YoutubeDL(
                    {
                        "proxy": os.environ.get("DOWNLOAD_PROXY"),
                        "verbose": True,
                        "outtmpl": filepath,
                        "logger": yt_logger,
                        "format": "bestaudio/best",
                        "max_filesize": 250 * 1024 * 1024,
                        "postprocessors": [
                            {
                                "key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "192",
                            }
                        ],
                        "postprocessor_args": {
                            "ffmpeg": ["-ac", "1", "-ar", "44100"]
                        },
                    }  # type: ignore
                ).extract_info(saved_url)
            )

            logging.info(info)
            duration = info.get("duration") if isinstance(info, dict) else None

        if duration is not None and duration >= 3 * 60:
            logging.error("Попытка транскрибации аудио больше 3 минут, отменено")
            return False

        files = os.listdir(dir)
        audio = [f for f in files if f.endswith(".mp3")]
        if len(audio) == 0:
            logging.error("Аудио для транскрибации не найдено")
            return False

        logging.info(os.environ.get("SPEECHKIT_API_SECRET"))
        with open(dir + "/" + audio[0], "rb") as file:
            client = ElevenLabs(
                api_key=os.environ.get("EVELEN_LABS_STT"),
                httpx_client=httpx.Client(
                    timeout=240, proxy=os.environ.get("DOWNLOAD_PROXY")
                ),
            )

            file.seek(0)
            audio_resp = await asyncio.to_thread(
                lambda: client.speech_to_text.convert(
                    file=file.read(),
                    model_id="scribe_v1",
                    tag_audio_events=True,
                    diarize=True,
                )
            )

            logging.info(audio_resp)
            words = cast(SpeechToTextChunkResponseModel, audio_resp).words or []
            text = build_named_speakers_text(words)
            if not text:
                text = (getattr(audio_resp, "text", "") or "").strip()
            if not text:
                text = "Не удалось распознать речь"

        html_text = wrap_as_spoiler(text)
        if len(html_text) > 1024:
            new_message = await message.reply_html(html_text)
            await message.edit_caption(new_message.link)
        else:
            await message.edit_caption(html_text, parse_mode="html")

    return True
