from telegram import InputMediaPhoto, Update
from telegram.ext import ContextTypes
from bs4 import BeautifulSoup

import aiohttp
import re
import logging

from consts import URL_REGEX
from handlers.handler import Handler

logger = logging.getLogger('download_controller')

class DownloadHandler(Handler):
    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.text is not None:
            urls = re.findall(URL_REGEX, update.message.text)

            for url in urls:
                for handlerPath, handler in {
                    'tiktok': self._load_tiktok,
                    'instagram.com': self._load_instagram,
                    'youtube.com': self._load_youtube,
                    'youtu.be': self._load_youtube,
                }.items():
                    if handlerPath in url:
                        logger.info(f'Получен url: {url}')
                        await handler(url, update, context)
                        return True

    async def _load_tiktok(self, url:str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            print("Тикток пошел")
            async with aiohttp.ClientSession() as session:
                logger.info('Запрос на получение информации')

                async with session.post("https://ttsave.app/download", data={'query': url, 'language_id': "1"}) as response:
                    bs = BeautifulSoup(await response.text(), 'html.parser')

                    video = [a.get('href') for a in bs.find_all('a', type="no-watermark") if a.get('href') is not None]
                    if len(video) > 0:
                        logger.info(f'Видео получено: {video}')
                        await update.message.reply_video(video[0])
                        logger.info('Видео отправлено')
                        return

                    images = [InputMediaPhoto(a.get('href')) for a in bs.find_all('a', type="slide") if a.get('href') is not None]
                    if len(images) > 0:
                        logger.info(f'Картинки получены: {images}')
                        for i in range(0, len(images), 10):
                            await update.message.reply_media_group(images[i:i+10])
                        logger.info('Картинки отправлены')
                        return

                    await update.message.reply_text("Ты плохой человек")
        except Exception as e:
            logger.exception(e)

    async def _load_instagram(self, url:str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            print("Инстаграм пошел")
            async with aiohttp.ClientSession() as session:
                async with session.get("http://8.215.8.243:1337/instagram2?url="+url) as response:
                    json = await response.json()
                    if json['status']:
                        video = json['result'][0]
                        logger.info(f'Получено видео: {video}')
                        await update.message.reply_video(video)
        except Exception as e:
            logger.exception(e)

    async def _load_youtube(self, url:str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            print("Youtube пошел")
            async with aiohttp.ClientSession() as session:
                async with session.get("http://8.215.8.243:1337/youtube", params={'url': url, 'type': 'video'}) as response:
                    print(await response.text())
                    json = await response.json()
        except Exception as e:
            logger.exception(e)
