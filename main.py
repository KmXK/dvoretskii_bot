from telegram import ForceReply, Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from bs4 import BeautifulSoup

import re
import json
import aiohttp

TOKEN = '***REMOVED***'
regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36'}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}!",
        reply_markup=ForceReply(selective=True)
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    urls = re.findall(regex, update.message.text)
    
    for url in urls:
        if 'tiktok' in url:
            try:
                """try to load video"""
                await load_video(url, update)
            except:
                try:
                    """try to load photos"""
                    await load_images(url, update)
                except:
                    await update.message.reply_text("Ты плохой человек")
                                            
    if (update.message.text != None and update.message.text == 'Да' or update.message.text == 'да'):
        print(update.message.from_user.id)
        if (update.message.from_user.id == ***REMOVED***):
            await update.message.reply_text('да')         
        else:
            await update.message.reply_text('Да') 
    
async def load_video(url: str, update: Update):
    async with aiohttp.ClientSession() as session:
        print('Start downloading video')
        async with session.get(url, headers=headers) as response:
            soap = BeautifulSoup(await response.text(), 'html.parser')
            data_str = soap.find(id="__UNIVERSAL_DATA_FOR_REHYDRATION__")
            data = json.loads(data_str.text)
            new_url = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]["video"]["playAddr"]
        async with session.get(new_url, headers=headers) as response:                                    
            if response.headers['content-type'] == 'video/mp4':
                video_data = await response.read()
                print("Downloaded video bytes:", len(video_data))
                await update.message.reply_video(video=video_data)

async def load_images(url: str, update: Update):
    async with aiohttp.ClientSession() as session:
        print('Start downloading images')
        async with session.post("https://ttsave.app/download", data={'query': url, 'language_id': "1"}) as response:                            
            bs = BeautifulSoup(await response.text(), 'html.parser')
            images = [InputMediaPhoto(a.get('href')) for a in bs.find_all('a', type="slide") if a.get('href') is not None]
            print("Download images complete")
            for i in range(0, len(images), 10):
                await update.message.reply_media_group(images[i:i+10])  
            
def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()