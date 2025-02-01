import base64
import logging
import re
from asyncio import sleep

import aiohttp
from telegram import InputMediaAudio, InputMediaPhoto, Update
from telegram.ext import ContextTypes

from steward.handlers.handler import Handler

logger = logging.getLogger("download_controller")

URL_REGEX = (
    r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)


class DownloadHandler(Handler):
    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                            await handler(url, update, context)
                        except Exception as e:
                            logger.exception(e)
                        return True

    async def _load_tiktok(
        self, url: str, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        logger.info("Тикток пошел")
        async with aiohttp.ClientSession() as session:
            logger.info("Запрос на получение информации")

            # async with session.post(
            #     "https://ttsave.app/download",
            #     data={"query": url, "language_id": "1"},
            # ) as response:
            #     bs = BeautifulSoup(await response.text(), "html.parser")

            #     video = [
            #         a.get("href")
            #         for a in bs.find_all("a", type="no-watermark")
            #         if a.get("href") is not None
            #     ]
            #     if len(video) > 0:
            #         logger.info(f"Видео получено: {video}")
            #         await update.message.reply_video(video[0])
            #         logger.info("Видео отправлено")
            #         return

            #     images = [
            #         InputMediaPhoto(a.get("href"))
            #         for a in bs.find_all("a", type="slide")
            #         if a.get("href") is not None
            #     ]
            #     if len(images) > 0:
            #         logger.info(f"Картинки получены: {images}")
            #         for i in range(0, len(images), 10):
            #             await update.message.reply_media_group(images[i : i + 10])
            #         logger.info("Картинки отправлены")
            #         return

            #     await update.message.reply_text("Ты плохой человек")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://8.215.8.243:1337/tiktok2?url=" + url
            ) as response:
                json = await response.json()
                if json["status"]:
                    video = json["result"].get("video")
                    images = json["result"].get("image")
                    if video is not None:
                        logger.info(f"Получено видео: {video}")
                        await update.message.reply_video(video)
                    elif images is not None:
                        audio = json["result"].get("audio")
                        if audio is not None:
                            audio = InputMediaAudio(
                                audio, filename="TikTok Audio", title="123"
                            )
                        logger.info(f"Картинки получены: {images}")
                        images = [InputMediaPhoto(href) for href in images]
                        for i in range(0, len(images), 10):
                            retry = 0
                            while retry < 5:
                                if retry == 2 and audio is not None:
                                    await update.message.reply_media_group([audio])
                                    await sleep(3)
                                    audio = None
                                
                                try:
                                    await update.message.reply_media_group(
                                        images[i : i + 10]
                                    )
                                    break
                                except Exception as e:
                                    logging.exception(e)
                                    await sleep(5)
                                    retry += 1
                            if i + 10 < len(images):
                                await sleep(2)

                        if audio is not None:
                            await update.message.reply_media_group([audio])
                        logger.info("Картинки отправлены")

                    # logger.info(f"Получено видео: {video}")
                    # new_url = (
                    #     "https://download.proxy.nigger.by/?password=***REMOVED***&download_url="
                    #     + base64.b64encode(video.encode("utf-8")).decode("utf-8")
                    # )
                    # logger.info(f"Video via proxy: {new_url}")
                    # await update.message.reply_video(new_url)

                    # await update.message.reply_video(video)

    async def _load_instagram(
        self, url: str, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        logger.info("Инстаграм пошел")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://8.215.8.243:1337/instagram2?url=" + url
            ) as response:
                json = await response.json()
                if json["status"]:
                    first = json["result"][0]
                    if 'd.rapidcdn.app' in first:
                        video = first
                        logger.info(f"Получено видео: {video}")
                        new_url = (
                            "https://download.proxy.nigger.by/?password=***REMOVED***&download_url="
                            + base64.b64encode(video.encode("utf-8")).decode("utf-8")
                        )
                        logger.info(f"Video via proxy: {new_url}")
                        await update.message.reply_video(video)
                    else:
                        images = [InputMediaPhoto(href) for href in json["result"]]
                        logger.info(f"Картинки получены: {images}")
                        for i in range(0, len(images), 10):
                            retry = 0
                            while retry < 5:
                                if retry == 2 and audio is not None:
                                    await update.message.reply_media_group([audio])
                                    await sleep(3)
                                    audio = None

                                try:
                                    await update.message.reply_media_group(
                                        images[i : i + 10]
                                    )
                                    break
                                except Exception as e:
                                    logging.exception(e)
                                    await sleep(5)
                                    retry += 1
                            if i + 10 < len(images):
                                await sleep(2)
                        logger.info("Картинки отправлены")

    async def _load_youtube(
        self, url: str, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        logger.info("Youtube пошел")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://8.215.8.243:1337/youtube",
                params={"url": url, "type": "video"},
            ) as response:
                logger.info(await response.text())
