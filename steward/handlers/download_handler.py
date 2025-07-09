import asyncio
import logging
import os
import re
import tempfile
import base64
import json
from urllib.parse import urlparse, parse_qs
from contextlib import ExitStack, asynccontextmanager
from typing import Any, Callable

import aiohttp
import youtube_dl
import yt_dlp
from aiohttp_socks import ProxyConnector
from telegram import InputFile, InputMediaPhoto, InputMediaVideo, Message

from steward.handlers.handler import Handler
from steward.helpers import morphy
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger("download_controller")
yt_logger = logging.getLogger("youtube_dl")
yt_logger.setLevel(logging.DEBUG)

URL_REGEX = (
    r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)

YT_LIMIT = "YT_LIMIT_OBJECT"


class DownloadHandler(Handler):
    # TODO: Make process pool

    async def chat(self, context):
        assert context.message.text
        urls = re.findall(URL_REGEX, context.message.text)

        for url in urls:
            for handlerPath, handlers in {
                "tiktok": [
                    self._get_video_wrapper("tiktok"),
                    self._get_images_wrapper("tiktok"),
                ],
                "instagram.com": [
                    self._load_instagram,
                    # self._get_video_wrapper(
                    #     "inst",
                    #     cookie_file=os.environ.get("INSTAGRAM_COOKIE_FILE"),
                    # ),
                    # self._get_images_wrapper(
                    #     "inst",
                    #     cookie_file=os.environ.get("INSTAGRAM_COOKIE_FILE"),
                    # ),
                ],
                "youtube.com": self._get_video_wrapper(
                    "youtube",
                    cookie_file=os.environ.get("YT_COOKIES_FILE"),
                    pre_call=lambda: check_limit(YT_LIMIT, 1, 10 * Duration.SECOND),
                ),
                "youtu.be": self._get_video_wrapper(
                    "youtube",
                    cookie_file=os.environ.get("YT_COOKIES_FILE"),
                    pre_call=lambda: check_limit(YT_LIMIT, 1, 10 * Duration.SECOND),
                ),
                "music.yandex": self._load_yandex_music,
            }.items():
                if handlerPath in url:
                    check_limit(YT_LIMIT, 15, Duration.MINUTE)
                    logger.info(f"Получен url: {url}")
                    if not isinstance(handlers, list):
                        handlers = [handlers]

                    # success = False
                    for handler in handlers:
                        success = False
                        for i in range(1):
                            try:
                                await handler(url, context.message)
                                success = True
                                break
                            except Exception as e:
                                logger.exception(e)
                        if success:
                            break

                    # if not success:
                    #     await context.message.reply_text("не смог =(")
                    return True

    async def _load_instagram(
        self,
        url: str,
        message: Message,
    ):
        url = f"https://download.proxy.nigger.by/igdl?url={url}"

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(connect=2)
        ) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"invalid response: {response}")

                json_resp = await response.json()

                medias = []

                for x in json_resp["url"]["data"]:
                    url = x["url"]
                    token = parse_qs(urlparse(url).query)["token"][0]
                    json_data = base64.urlsafe_b64decode(token.split(".")[1] + ("=" * (4 - (len(token.split(".")[1]) % 4))))
                    filename = json.loads(json_data)["filename"]
                    if filename.endswith("mp4"):
                        medias.append((url, True))
                    else:
                        medias.append((url, False))

                # unique
                medias = sorted(set(medias), key=lambda x: medias.index(x))

                if len(medias) > 0:
                    await self._download_and_send_medias(message, medias)

    async def _load_yandex_music(
        self,
        url: str,
        message: Message,
    ):
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
                # await message.reply_text("Ошибка авторизации, попробуй позже =(")
                return

            with open(os.path.join(dir, os.listdir(dir)[0]), "rb") as file:
                logger.info(file)
                await message.reply_audio(file, filename=file.name)

    def _get_video_wrapper(
        self,
        type_name: str,
        cookie_file: str | None = None,
        pre_call: Callable[[], Any] = lambda: None,
    ):
        async def wrapper(
            url: str,
            message: Message,
        ):
            pre_call()

            logger.info(f"trying get video from {type_name}...")

            with tempfile.TemporaryDirectory(prefix=f"{type_name}_") as dir:
                filepath = dir + "/file"
                info = yt_dlp.YoutubeDL(
                    {
                        "proxy": os.environ.get("DOWNLOAD_PROXY"),
                        "verbose": True,
                        "outtmpl": filepath,
                        "logger": yt_logger,
                        "cookiefile": cookie_file,
                        "format": "(bv[filesize<=250M]+ba)/best",
                        "format_sort": ["ext:mp4", "res:1080"],
                        "max_filesize": 250 * 1024 * 1024,
                    }
                ).extract_info(url)

                width: str | None = None
                height: str | None = None
                if isinstance(info, dict):
                    width = info.get("width")  # type: ignore
                    height = info.get("height")  # type: ignore

                # fix
                files = os.listdir(dir)
                logging.info(os.listdir(dir))

                filepath = dir + "/" + files[0]

                with open(filepath, "rb") as file:
                    await message.reply_video(
                        InputFile(file, filename=f"{type_name} Video"),
                        supports_streaming=True,
                        width=int(width) if width is not None else None,
                        height=int(height) if height is not None else None,
                    )

        return wrapper

    def _get_images_wrapper(
        self,
        type_name: str,
        cookie_file: str | None = None,
    ):
        async def wrapper(
            url: str,
            message: Message,
        ):
            logger.info(f"trying get images from {type_name}...")

            with tempfile.TemporaryDirectory(prefix=f"{type_name}_") as dir:
                process = await asyncio.create_subprocess_exec(
                    "gallery-dl",
                    *(
                        [
                            "--proxy",
                            os.environ.get("DOWNLOAD_PROXY") or "",
                        ]
                        if os.environ.get("DOWNLOAD_PROXY")
                        else []
                    ),
                    "--verbose",
                    "-f",
                    "{num}.{extension}",
                    "-D",
                    dir,
                    *(
                        [
                            "-C",
                            cookie_file,
                        ]
                        if cookie_file
                        else []
                    ),
                    url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()
                logger.info(
                    f"gallery-dl process done: stdout={stdout.decode(errors='replace')}, stderr={stderr.decode(errors='replace')}"
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

                await self._send_images(message, images)

                if len(audios) > 0:
                    with open(os.path.join(dir, audios[0]), "rb") as file:
                        await message.reply_audio(
                            file,
                            filename="Audio",
                        )

        return wrapper

    async def _send_video(
        self,
        message: Message,
        url: str,
    ):
        # будет удалён при закрытии
        async with self._download_file(url) as file:
            await message.reply_video(
                InputFile(file, filename="TikTok Video"),
                disable_notification=True,
                supports_streaming=True,
            )

    async def _download_and_send_medias(
        self,
        message: Message,
        videosOrImages: list[tuple[str, bool]],
        retries_count: int = 5,
        use_proxy=False,
    ):
        logger.info(
            f"Отправляется {morphy.make_agree_with_number('картинка', len(videosOrImages))}"
        )

        files_tasks = [self._download_file(url, use_proxy=use_proxy) for url, _ in videosOrImages]

        try:
            results = await asyncio.gather(
                *[task.__aenter__() for task in files_tasks],
                return_exceptions=True,
            )

            logger.info(results)

            exceptions = [exc for exc in results if isinstance(exc, Exception)]
            if len(exceptions) > 0:
                raise ExceptionGroup("", exceptions)

            logger.info(exceptions)

            medias = [
                InputMediaPhoto(file) if not videosOrImages[i][1] else InputMediaVideo(file)
                for i, file in enumerate(results)
                if not isinstance(file, BaseException)
            ]

            for i in range(0, len(medias), 10):
                retry = 0
                while retry < retries_count:
                    try:
                        await message.reply_media_group(
                            medias[i : i + 10],
                            disable_notification=True,
                        )
                        break
                    except Exception as e:
                        logging.exception(e)
                        await asyncio.sleep(5)
                        retry += 1

                # wait if not last
                if i + 10 < len(images):
                    await asyncio.sleep(2)

            logger.info("Картинки отправлены")

        except Exception as e:
            for task in files_tasks:
                await task.__aexit__(None, None, None)
            raise e

    async def _send_images(
        self,
        message: Message,
        images: list[str],
        retries_count: int = 5,
    ):
        logger.info(
            f"Отправляется {morphy.make_agree_with_number('картинка', len(images))}"
        )

        try:
            # exceptions = [exc for exc in results if isinstance(exc, Exception)]
            # if len(exceptions) > 0:
            #     raise ExceptionGroup("", exceptions)

            medias = []

            with ExitStack() as stack:
                for image_path in images:
                    file = stack.enter_context(open(image_path, "rb"))
                    medias.append(InputMediaPhoto(file))

                for i in range(0, len(medias), 10):
                    retry = 0
                    while retry < retries_count:
                        try:
                            await message.reply_media_group(
                                medias[i : i + 10],
                                disable_notification=True,
                            )
                            break
                        except Exception as e:
                            logging.exception(e)
                            await asyncio.sleep(5)
                            retry += 1

                    # wait if not last
                    if i + 10 < len(images):
                        await asyncio.sleep(2)

            logger.info("Картинки отправлены")

        except Exception as e:
            raise e

    async def _send_images_by_url(
        self,
        message: Message,
        urls: list[str],
        retries_count: int = 5,
    ):
        logger.info(
            f"Отправляется {morphy.make_agree_with_number('картинка', len(urls))}: {urls}"
        )

        try:
            medias = []

            for image_url in urls:
                medias.append(InputMediaPhoto(image_url))

            for i in range(0, len(medias), 10):
                retry = 0
                while retry < retries_count:
                    try:
                        await message.reply_media_group(
                            medias[i : i + 10],
                            disable_notification=True,
                        )
                        break
                    except Exception as e:
                        logging.exception(e)
                        await asyncio.sleep(5)
                        retry += 1

                # wait if not last
                if i + 10 < len(urls):
                    await asyncio.sleep(2)

            logger.info("Картинки отправлены")

        except Exception as e:
            raise e

    @asynccontextmanager
    async def _download_file(self, url: str, use_proxy=False):
        logger.info(f"Скачиваем файл: {url}")
        with tempfile.TemporaryFile("r+b") as file:
            logger.info(f"Создан файл {file.name}")

            async def get_url_content_to_file(url: str):
                connector = None
                if use_proxy and os.environ.get("DOWNLOAD_PROXY"):
                    connector = ProxyConnector.from_url(
                        os.environ.get("DOWNLOAD_PROXY") or ""
                    )

                async with aiohttp.ClientSession(
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(connect=2),
                ) as session:
                    async with session.get(url) as response:
                        while True:
                            chunk = await response.content.readany()
                            if not chunk:
                                break
                            file.write(chunk)

            await get_url_content_to_file(url)

            logger.info("Файл был скачен")

            file.seek(0)

            try:
                yield file
            except Exception as e:
                logger.exception(e)
                raise e
