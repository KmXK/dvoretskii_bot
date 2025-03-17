import asyncio
import base64
import logging
import os
import re
import tempfile
from contextlib import ExitStack, asynccontextmanager
from typing import Any, Callable
from urllib.parse import urlencode
from aiohttp_socks import ProxyConnector

import aiohttp
import youtube_dl
import yt_dlp
from telegram import InputFile, InputMediaPhoto, Message

from steward.helpers.limiter import Duration, check_limit
from steward.handlers.handler import Handler
from steward.helpers import morphy

logger = logging.getLogger("download_controller")
yt_logger = logging.getLogger("youtube_dl")
yt_logger.setLevel(logging.DEBUG)

URL_REGEX = (
    r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)

YT_LIMIT = 'YT_LIMIT_OBJECT'


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

                json = await response.json()

                data = json["url"]["data"]

                videos = [x["url"] for x in data if "rapidcdn" in x["url"]]
                images = [x["url"] for x in data if "rapidcdn" not in x["url"]]

                videos = sorted(set(videos), key=lambda x: videos.index(x))
                images = sorted(set(images), key=lambda x: images.index(x))

                for video in videos:
                    await self._send_video(message, video)

                if len(images) > 0:
                    await self._send_images_by_url(message, images)

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
                youtube_dl.YoutubeDL({
                    "verbose": True,
                    "outtmpl": filepath,
                    "logger": yt_logger,
                    "retries": 0,
                }).download([url.split("?")[0]])
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
                info = yt_dlp.YoutubeDL({
                    "proxy": "socks5://***REMOVED***:***REMOVED***@nigger.by:61228",
                    "verbose": True,
                    "outtmpl": filepath,
                    "logger": yt_logger,
                    "cookiefile": cookie_file,
                    "format": "(bv[filesize<=250M]+ba)/best",
                    "format_sort": ["ext:mp4", "res:1080"],
                    "max_filesize": 250 * 1024 * 1024,
                }).extract_info(url)

                width: str | None = None
                height: str | None = None
                if isinstance(info, dict):
                    width = info.get('width') # type: ignore
                    height = info.get('height') # type: ignore

                # fix
                files = os.listdir(dir)
                logging.info(os.listdir(dir))

                filepath = dir + '/' + files[0]

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
                    "--proxy",
                    "socks5://***REMOVED***:***REMOVED***@nigger.by:61228",
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

                all_files = [os.path.join(dir, x) for x in os.listdir(dir)]
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
        use_proxy: bool = False,
    ):
        if use_proxy:
            logger.info(f"Хотим скачать видео через прокси: {url}")
            url = self._get_proxy_url(url)

        # будет удалён при закрытии
        async with self._download_file(url) as file:
            await message.reply_video(
                InputFile(file, filename="TikTok Video"),
                disable_notification=True,
                supports_streaming=True,
            )

    async def _download_and_send_images(
        self,
        message: Message,
        images: list[str],
        retries_count: int = 5,
        use_proxy = False,
    ):
        logger.info(
            f"Отправляется {morphy.make_agree_with_number('картинка', len(images))}"
        )

        files_tasks = [self._download_file(url, use_proxy=use_proxy) for url in images]

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
                InputMediaPhoto(file)
                for file in results
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

        # files_tasks = [self._download_file(url) for url in images]

        try:
            # results = await asyncio.gather(
            #     *[task.__aenter__() for task in files_tasks],
            #     return_exceptions=True,
            # )

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
            # for task in files_tasks:
            #     await task.__aexit__(None, None, None)
            raise e

    async def _send_images_by_url(
        self,
        message: Message,
        urls: list[str],
        retries_count: int = 5,
    ):
        logger.info(
            f"Отправляется {morphy.make_agree_with_number('картинка', len(urls))}"
        )

        # files_tasks = [self._download_file(url) for url in images]

        try:
            # results = await asyncio.gather(
            #     *[task.__aenter__() for task in files_tasks],
            #     return_exceptions=True,
            # )

            # exceptions = [exc for exc in results if isinstance(exc, Exception)]
            # if len(exceptions) > 0:
            #     raise ExceptionGroup("", exceptions)

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
            # for task in files_tasks:
            #     await task.__aexit__(None, None, None)
            raise e

    def _get_proxy_url(self, url: str) -> str:
        return "https://download.proxy.nigger.by/?" + urlencode({
            "password": "***REMOVED***",
            "download_url": base64.b64encode(url.encode()).decode(),
        })

    @asynccontextmanager
    async def _download_file(self, url: str, use_proxy = False):
        logger.info(f"Скачиваем файл: {url}")
        with tempfile.TemporaryFile("r+b") as file:
            logger.info(f"Создан файл {file.name}")

            async def get_url_content_to_file(url: str):
                connector = None
                if use_proxy:
                    connector = ProxyConnector.from_url('socks5://***REMOVED***:***REMOVED***@nigger.by:61228')

                async with aiohttp.ClientSession(
                    # connector=connector,
                    timeout=aiohttp.ClientTimeout(connect=2),
                ) as session:
                    async with session.get(
                        url
                    ) as response:
                        while True:
                            chunk = await response.content.readany()
                            if not chunk:
                                break
                            file.write(chunk)

            # try:
            await get_url_content_to_file(url)
            # except Exception as e:
            #     logger.exception(e)
            #     await get_url_content_to_file(self._get_proxy_url(url))

            logger.info("Файл был скачен")

            file.seek(0)

            try:
                yield file
            except Exception as e:
                logger.exception(e)
                raise e
