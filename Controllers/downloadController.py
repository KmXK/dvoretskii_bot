from telegram import InputMediaPhoto, Update
from telegram.ext import ContextTypes
from bs4 import BeautifulSoup
from pytube import YouTube

import aiohttp
import re
import os
import logging

LINK_REGEX = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'

class DownloadController(object):
    
    async def load_tiktok(self, url:str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://ttsave.app/download", data={'query': url, 'language_id': "1"}) as response:                             
                    bs = BeautifulSoup(await response.text(), 'html.parser')
                    
                    video = [a.get('href') for a in bs.find_all('a', type="no-watermark") if a.get('href') is not None]
                    if len(video) > 0:
                        await update.message.reply_video(video[0])
                        return
                    
                    images = [InputMediaPhoto(a.get('href')) for a in bs.find_all('a', type="slide") if a.get('href') is not None]        
                    if len(images) > 0:
                        for i in range(0, len(images), 10):
                            await update.message.reply_media_group(images[i:i+10])  
                        return
            
                    await update.message.reply_text("Ты плохой человек")
        except Exception as e:
            logging.exception(e)
        return
    
    async def load_youtube(self, url:str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            filename = YouTube(url).streams.get_highest_resolution().download()
            await update.message.reply_video(filename)
            os.remove(filename)                
        except Exception as e:
            logging.exception(e)
        return
    
    async def try_download(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.text is not None:
            urls = re.findall(LINK_REGEX, update.message.text)
            for url in urls:
                if 'tiktok' in url:
                    await self.load_tiktok(url, update, context)
                    return
                if 'youtube.com' or 'youtu.be' in url:
                    await self.load_youtube(url, update, context)
                    return