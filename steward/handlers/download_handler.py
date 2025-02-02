import base64
import logging
import re
import tempfile
from asyncio import sleep
from contextlib import asynccontextmanager
from urllib.parse import urlencode

import aiohttp
from telegram import InputFile, InputMediaAudio, InputMediaPhoto, Message, Update
from telegram.ext import ContextTypes

from steward.handlers.handler import Handler

logger = logging.getLogger("download_controller")

URL_REGEX = (
    r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)


class DownloadHandler(Handler):
    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # todo: remove after adding context to handlers
        assert update.message is not None

        if update.message.text is not None:
            urls = re.findall(URL_REGEX, update.message.text)

            for url in urls:
                for handlerPath, handler in {
                    "tiktok": self._load_tiktok,
                    "instagram.com": self._load_instagram,
                    "youtube.com": self._load_youtube,
                    "youtu.be": self._load_youtube,
                }.items():
                    if handlerPath in url:
                        logger.info(f"Получен url: {url}")
                        try:
                            await handler(url, update.message)
                        except Exception as e:
                            logger.exception(e)
                        return True

    async def _load_tiktok(
        self,
        url: str,
        message: Message,
    ):
        logger.info("Тикток пошел")
        # async with aiohttp.ClientSession() as session:
        #     logger.info("Запрос на получение информации")

        #     async with session.post(
        #         "https://ttsave.app/download",
        #         data={"query": url, "language_id": "1"},
        #     ) as response:
        #         bs = BeautifulSoup(await response.text(), "html.parser")

        #         video = [
        #             a.get("href")
        #             for a in bs.find_all("a", type="no-watermark")
        #             if a.get("href") is not None
        #         ]
        #         if len(video) > 0:
        #             logger.info(f"Видео получено: {video}")
        #             await message.reply_video(video[0])
        #             logger.info("Видео отправлено")
        #             return

        #         images = [
        #             InputMediaPhoto(a.get("href"))
        #             for a in bs.find_all("a", type="slide")
        #             if a.get("href") is not None
        #         ]
        #         if len(images) > 0:
        #             logger.info(f"Картинки получены: {images}")
        #             for i in range(0, len(images), 10):
        #                 await message.reply_media_group(images[i : i + 10])
        #             logger.info("Картинки отправлены")
        #             return

        #         await message.reply_text("Ты плохой человек")

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
                            audio = InputMediaAudio(
                                audio,
                                filename="TikTok Audio",
                                title="123",
                            )
                            await message.reply_media_group([audio])
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
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://8.215.8.243:1337/youtube",
                params={"url": url, "type": "video"},
            ) as response:
                logger.info(await response.text())

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
        async with self._get_file(url, "TikTok Video") as input_file:
            await message.reply_video(
                input_file,
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
        logger.info(f"Отправляются картинки: {images}")
        medias = [
            InputMediaPhoto(href if use_proxy else self._get_proxy_url(href))
            for href in images
        ]

        for i in range(0, len(images), 10):
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

    def _get_proxy_url(self, url: str) -> str:
        return "https://download.proxy.nigger.by/?" + urlencode({
            "password": "***REMOVED***",
            "download_url": base64.b64encode(url.encode()).decode(),
        })

    @asynccontextmanager
    async def _get_file(self, url: str, filename: str):
        logger.info(f"Скачиваем файл: {url}")
        with tempfile.TemporaryFile("r+b") as file:
            logger.info(f"Создан файл {file.name}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    while True:
                        chunk = await response.content.readany()
                        if not chunk:
                            break
                        file.write(chunk)

            logger.info("Файл был скачен")

            file.seek(0)

            yield InputFile(file, filename)
