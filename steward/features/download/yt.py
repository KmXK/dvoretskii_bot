import asyncio
import base64
import json
import logging
import os
import tempfile
import uuid
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import aiohttp
import youtube_dl
import yt_dlp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Message,
)

from steward.data.repository import Repository
from steward.features.download.callbacks import (
    download_and_send_medias,
    send_images,
)
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger("download_controller")
yt_logger = logging.getLogger("youtube_dl")
yt_logger.setLevel(logging.DEBUG)

URL_REGEX = (
    r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)

YT_LIMIT = "YT_LIMIT_OBJECT"

DOWNLOAD_TYPE_MAP = {
    "tiktok": "tiktok",
    "instagram.com": "reels",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "pinterest.com": "pinterest",
    "pin.it": "pinterest",
    "music.yandex": "music",
}


async def load_instagram(repository: Repository, url: str, message: Message) -> None:
    url = f"https://download.proxy.nigger.by/igdl?url={url}"

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(connect=2)
    ) as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"invalid response: {response}")

            json_resp = await response.json()

            medias: list[tuple[str, bool]] = []

            for x in json_resp["url"]["data"]:
                media_url = x["url"]
                token = parse_qs(urlparse(media_url).query)["token"][0]
                payload = token.split(".")[1]
                json_data = base64.urlsafe_b64decode(
                    payload + ("=" * (4 - (len(payload) % 4)))
                )
                filename = json.loads(json_data)["filename"]
                medias.append((media_url, filename.endswith("mp4")))

            medias = sorted(set(medias), key=lambda x: medias.index(x))

            if len(medias) > 0:
                await download_and_send_medias(
                    repository, message, medias, use_proxy=True
                )


async def load_yandex_music(_repository: Repository, url: str, message: Message) -> None:
    logger.info("Yandex Music пошла")
    logger.info(url.split("?")[0])

    with tempfile.TemporaryDirectory(prefix="ym_") as dir:
        filepath = dir + "/%(title)s"
        try:
            youtube_dl.YoutubeDL(
                {
                    "verbose": True,
                    "outtmpl": filepath,
                    "logger": yt_logger,
                    "retries": 0,
                }
            ).download([url.split("?")[0]])
        except youtube_dl.DownloadError:
            logger.error("Ошибка авторизации, попробуй позже =(")
            return

        with open(os.path.join(dir, os.listdir(dir)[0]), "rb") as file:
            logger.info(file)
            await message.reply_audio(file, filename=file.name)


def make_video_loader(
    type_name: str,
    cookie_file: str | None = None,
    pre_call: Callable[[], Any] = lambda: None,
):
    async def wrapper(repository: Repository, url: str, message: Message) -> None:
        pre_call()

        logger.info(f"trying get video from {type_name}...")

        with tempfile.TemporaryDirectory(prefix=f"{type_name}_") as dir:
            filepath = dir + "/file"
            info = await asyncio.to_thread(
                lambda: yt_dlp.YoutubeDL(
                    {
                        "proxy": os.environ.get("DOWNLOAD_PROXY"),
                        "verbose": True,
                        "outtmpl": filepath,
                        "logger": yt_logger,
                        "cookiefile": cookie_file,
                        "format": "(bv+ba)/best",
                        "format_sort": ["ext:mp4", "res:1080"],
                        "max_filesize": 250 * 1024 * 1024,
                    }  # type: ignore
                ).extract_info(url)
            )

            width: Any = None
            height: Any = None
            if isinstance(info, dict):
                width = info.get("width", 0)
                height = info.get("height", 0)

            files = os.listdir(dir)
            logging.info(files)

            filepath = dir + "/" + files[0]

            reply_markup = None
            duration = info.get("duration") if isinstance(info, dict) else None
            if duration is not None and duration < 3 * 60:
                link_id = uuid.uuid4().hex
                repository.db.saved_links.add(link_id, url)
                await repository.save()
                reply_markup = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Текст",
                                callback_data=f"download:trans|{link_id}",
                            ),
                        ],
                    ]
                )

            with open(filepath, "rb") as file:
                await message.reply_video(
                    InputFile(file, filename=f"{type_name} Video"),
                    supports_streaming=True,
                    width=int(width) if width is not None else None,
                    height=int(height) if height is not None else None,
                    reply_markup=reply_markup,
                )

            logger.info(f"video {type_name} downloaded successfully")

    return wrapper


def make_images_loader(
    type_name: str,
    cookie_file: str | None = None,
):
    async def wrapper(_repository: Repository, url: str, message: Message) -> None:
        logger.info(f"trying get images from {type_name}...")

        with tempfile.TemporaryDirectory(prefix=f"{type_name}_") as dir:
            args: list[str] = []
            if os.environ.get("DOWNLOAD_PROXY"):
                args += ["--proxy", os.environ.get("DOWNLOAD_PROXY") or ""]
            args += ["--verbose", "-f", "{num}.{extension}", "-D", dir]
            if cookie_file:
                args += ["-C", cookie_file]
            args.append(url)

            process = await asyncio.create_subprocess_exec(
                "gallery-dl",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            logger.info(
                "gallery-dl process done: stdout=%s, stderr=%s",
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
            )

            if process.returncode != 0:
                raise Exception(
                    f"gallery-dl exited with error {process.returncode}"
                )

            all_files = [
                os.path.join(dir, x)
                for x in sorted(
                    os.listdir(dir), key=lambda x: f"{int(x.split('.')[0]):03d}"
                )
            ]
            images = [x for x in all_files if not x.endswith(".mp3")]
            audios = [x for x in all_files if x.endswith(".mp3")]

            await send_images(message, images)

            if len(audios) > 0:
                with open(os.path.join(dir, audios[0]), "rb") as file:
                    await message.reply_audio(file, filename="Audio")

    return wrapper


def build_dispatch(repository: Repository) -> dict[str, list]:
    yt_pre = lambda: check_limit(YT_LIMIT, 1, 10 * Duration.SECOND)

    def _bind(loader):
        async def runner(url, message):
            await loader(repository, url, message)
        return runner

    return {
        "tiktok": [
            _bind(make_video_loader("tiktok")),
            _bind(make_images_loader("tiktok")),
        ],
        "instagram.com": [
            lambda url, message: load_instagram(repository, url, message),
        ],
        "youtube.com": [_bind(make_video_loader("youtube", pre_call=yt_pre))],
        "youtu.be": [_bind(make_video_loader("youtube", pre_call=yt_pre))],
        "pinterest.com": [
            _bind(make_video_loader("pinterest")),
            _bind(make_images_loader("pinterest")),
        ],
        "pin.it": [
            _bind(make_video_loader("pinterest")),
            _bind(make_images_loader("pinterest")),
        ],
        "music.yandex": [
            lambda url, message: load_yandex_music(repository, url, message),
        ],
    }
