import base64
import logging
import os
import re
import tempfile
from asyncio import sleep
from contextlib import ExitStack, asynccontextmanager
from urllib.parse import urlencode

import aiohttp
import gallery_dl
import gallery_dl.path
import youtube_dl
import yt_dlp
from pyrate_limiter import Duration
from telegram import InputFile, InputMediaPhoto, Message

from steward.handlers.handler import Handler
from steward.helpers import morphy
from steward.helpers.limiter import check_limit

logger = logging.getLogger("download_controller")
yt_logger = logging.getLogger("youtube_dl")
yt_logger.setLevel(logging.DEBUG)

URL_REGEX = (
    r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)


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
                    self._get_video_wrapper("inst"),
                    self._get_images_wrapper("inst"),
                ],
                "youtube.com": self._get_video_wrapper("youtube"),
                "youtu.be": self._get_video_wrapper("youtube"),
                "music.yandex": self._load_yandex_music,
            }.items():
                if handlerPath in url:
                    logger.info(f"Получен url: {url}")
                    if not isinstance(handlers, list):
                        handlers = [handlers]

                    success = False
                    for handler in handlers:
                        try:
                            await handler(url, context.message)
                            success = True
                            break
                        except Exception as e:
                            logger.exception(e)

                    if not success:
                        await context.message.reply_text("не смог =(")
                    return True

    async def _load_yandex_music(
        self,
        url: str,
        message: Message,
    ):
        check_limit(self, 1, 10 * Duration.SECOND)

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
    ):
        async def wrapper(
            url: str,
            message: Message,
        ):
            logger.info(f"trying get video from {type_name}...")

            with tempfile.TemporaryDirectory(prefix=f"{type_name}_") as dir:
                filepath = dir + "/file"
                logger.info(
                    yt_dlp.YoutubeDL({
                        "verbose": True,
                        "outtmpl": filepath,
                        "logger": yt_logger,
                    }).extract_info(url, download=True)
                )

                with open(filepath, "rb") as file:
                    await message.reply_video(
                        InputFile(file, filename=f"{type_name} Video"),
                        supports_streaming=True,
                    )

        return wrapper

    def _get_images_wrapper(
        self,
        type_name: str,
    ):
        async def wrapper(
            url: str,
            message: Message,
        ):
            logger.info(f"trying get images from {type_name}...")

            with tempfile.TemporaryDirectory(prefix=f"{type_name}_") as dir:

                class CustomPath(gallery_dl.path.PathFormat):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        self.i = 1

                    def build_path(self):
                        super().build_path()
                        i = self.i
                        self.i += 1
                        self.temppath = self.realpath = self.path = os.path.join(
                            dir,
                            re.sub(
                                r"(.*)\.(?P<extension>[^\.]+)$",
                                lambda m: f"{i}.{m.group('extension')}",
                                str(self.filename),
                            ),
                        )

                # TODO: cringe
                gallery_dl.path.PathFormat = CustomPath

                job = gallery_dl.job.DownloadJob(url)
                job.initialize()
                job.run()

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
                            await sleep(5)
                            retry += 1

                    # wait if not last
                    if i + 10 < len(images):
                        await sleep(2)

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
    async def _download_file(self, url: str):
        logger.info(f"Скачиваем файл: {url}")
        with tempfile.TemporaryFile("r+b") as file:
            logger.info(f"Создан файл {file.name}")

            async def get_url_content_to_file(url: str):
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(connect=2)
                ) as session:
                    async with session.get(url) as response:
                        while True:
                            chunk = await response.content.readany()
                            if not chunk:
                                break
                            file.write(chunk)

            try:
                await get_url_content_to_file(url)
            except Exception as e:
                logger.exception(e)
                await get_url_content_to_file(self._get_proxy_url(url))

            logger.info("Файл был скачен")

            file.seek(0)

            yield file
