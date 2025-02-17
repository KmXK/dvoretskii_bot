import asyncio
import base64
import logging
import os
import re
import tempfile
from asyncio import sleep
from contextlib import asynccontextmanager
from os import environ
from urllib.parse import urlencode

import aiohttp
import youtube_dl
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
    async def chat(self, context):
        assert context.message.text
        urls = re.findall(URL_REGEX, context.message.text)

        for url in urls:
            for handlerPath, handler in {
                "tiktok": self._load_tiktok,
                "instagram.com": self._load_instagram,
                "youtube.com": self._load_youtube,
                "youtu.be": self._load_youtube,
                "music.yandex": self._load_yandex_music,
            }.items():
                if handlerPath in url:
                    logger.info(f"Получен url: {url}")
                    try:
                        await handler(url, context.message)
                    except Exception as e:
                        logger.exception(e)
                    return True

    async def _load_tiktok(
        self,
        url: str,
        message: Message,
    ):
        logger.info("Тикток пошел")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://8.215.8.243:1337/tiktok2?url=" + url
            ) as response:
                json = await response.json()
                if json["status"]:
                    video = json["result"].get("video")
                    images = json["result"].get("image")
                    if video is not None:
                        await self._send_video(message, video)
                    elif images is not None:
                        await self._send_images(message, images)

                        audio = json["result"].get("audio")
                        if audio is not None:
                            logger.info(f"Получено аудио: {audio}")
                            async with self._download_file(audio) as file:
                                await message.reply_audio(file, filename="TikTok Audio")
                                logger.info("Аудио отправлено")

    async def _load_instagram(
        self,
        url: str,
        message: Message,
    ):
        logger.info("Инстаграм пошел")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://8.215.8.243:1337/instagram2?",
                params={"url": url},
            ) as response:
                json = await response.json()
                if json["status"]:
                    first: str = json["result"][0]
                    if "d.rapidcdn.app" in first:
                        await self._send_video(message, first)
                    else:
                        await self._send_images(message, json["result"])

    async def _load_youtube(
        self,
        url: str,
        message: Message,
    ):
        logger.info("Youtube пошел")

        with tempfile.TemporaryDirectory(prefix="yt_") as dir:
            filepath = dir + "/file"
            youtube_dl.YoutubeDL({
                "proxy": "socks5://***REMOVED***:***REMOVED***@nigger.by:61228",
                "verbose": True,
                "cookiefile": environ.get("YT_COOKIES_FILE"),
                "outtmpl": filepath,
                "logger": yt_logger,
            }).download([url])

            with open(filepath, "rb") as file:
                await message.reply_video(
                    InputFile(file, filename="Youtube Video"),
                    supports_streaming=True,
                )

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
        use_proxy: bool = False,
        retries_count: int = 5,
    ):
        logger.info(
            f"Отправляется {morphy.make_agree_with_number('картинка', len(images))}"
        )

        files_tasks = [self._download_file(url) for url in images]

        try:
            results = await asyncio.gather(
                *[task.__aenter__() for task in files_tasks],
                return_exceptions=True,
            )

            exceptions = [exc for exc in results if isinstance(exc, Exception)]
            if len(exceptions) > 0:
                raise ExceptionGroup("", exceptions)

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
                        await sleep(5)
                        retry += 1

                # wait if not last
                if i + 10 < len(images):
                    await sleep(2)

            logger.info("Картинки отправлены")

        except Exception as e:
            for task in files_tasks:
                await task.__aexit__(None, None, None)
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
