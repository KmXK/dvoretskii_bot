from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, ContextTypes, MessageHandler, filters
from bs4 import BeautifulSoup

import re
import json
import aiohttp
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(filename='main.log', encoding='utf-8', level=logging.DEBUG)

TOKEN = '***REMOVED***'
regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36'}
popusk_user_id = ***REMOVED***


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    urls = re.findall(regex, update.message.text)
    
    for url in urls:
        if 'tiktok' in url:
            try:
                logging.info("Пробуем скачать видео")
                await load_video(url, update)
            except:
                try:
                    logging.info("Пробуем скачать картинки")
                    await load_images(url, update)
                except Exception as e:
                    logging.exception(e)
                    await update.message.reply_text("Ты плохой человек")
                                            
    if (update.message.text != None and update.message.text == 'сосал?' or update.message.text == 'Сосал?'):
        logging.info(f"Id пользователя который отправил сообщение: {update.message.from_user.id}")
        if (update.message.from_user.id == popusk_user_id):
            await update.message.reply_text('Нет')         
        else:
            await update.message.reply_text('Да') 
    
async def load_video(url: str, update: Update):
    
    async with aiohttp.ClientSession() as session:
        logging.info('Запрос на загрузку видео')
        
        async with session.get(url, headers=headers) as response:
            soap = BeautifulSoup(await response.text(), 'html.parser')
            data_str = soap.find(id="__UNIVERSAL_DATA_FOR_REHYDRATION__")
            data = json.loads(data_str.text)
            new_url = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]["video"]["playAddr"]
            logging.info('Получена ссылка для скачивания')
    
        async with session.get(new_url, headers=headers) as response:                                    
            if response.headers['content-type'] == 'video/mp4':
                video_data = await response.read()
                logging.info('Видео получено')
                
                await update.message.reply_video(video=video_data)
                
                logging.info('Видео отправлено')

async def load_images(url: str, update: Update):
    
    async with aiohttp.ClientSession() as session:
        logging.info('Запрос на загрузку картинок')
        
        async with session.post("https://ttsave.app/download", data={'query': url, 'language_id': "1"}) as response:                            
            bs = BeautifulSoup(await response.text(), 'html.parser')
            images = [InputMediaPhoto(a.get('href')) for a in bs.find_all('a', type="slide") if a.get('href') is not None]
            logging.info('Картинки получены')
            
            for i in range(0, len(images), 10):
                await update.message.reply_media_group(images[i:i+10])  
            
            logging.info('Картинки отправлены')
            
            
def main():
    application = Application\
        .builder().token(TOKEN)\
        .read_timeout(300).write_timeout(300).pool_timeout(300).connect_timeout(300).media_write_timeout(300)\
        .build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()