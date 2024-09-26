from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from bs4 import BeautifulSoup

import re
import json
import aiohttp
import logging
import uuid
import random

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TOKEN = '***REMOVED***'
regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36'}


db = json.loads(open('db.json').read())

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db_message_response(update, context)
    
    urls = re.findall(regex, update.message.text)
    
    for url in urls:
        if 'tiktok' in url:
            
            async with aiohttp.ClientSession() as session:
                logging.info('Запрос на получение информации')
            
                async with session.post("https://ttsave.app/download", data={'query': url, 'language_id': "1"}) as response:                             
                    bs = BeautifulSoup(await response.text(), 'html.parser')
                    
                    video = [a.get('href') for a in bs.find_all('a', type="no-watermark") if a.get('href') is not None]
                    if len(video) > 0:
                        logging.info('Видео получено')
                        await update.message.reply_video(video[0])
                        logging.info('Видео отправлено')
                        return
                    
                    images = [InputMediaPhoto(a.get('href')) for a in bs.find_all('a', type="slide") if a.get('href') is not None]        
                    if len(images) > 0:
                        logging.info('Картинки получены')
                        for i in range(0, len(images), 10):
                            await update.message.reply_media_group(images[i:i+10])  
                        logging.info('Картинки отправлены')
                        return
            
                    await update.message.reply_text("Ты плохой человек")
    
    
    
async def db_message_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Id пользователя который отправил сообщение: {update.message.from_user.id}")
    
    rules_with_same_text = [rule for rule in db['rules'] if rule['text'] == update.message.text]
    rules_with_same_user_id = [rule for rule in rules_with_same_text if rule['from'] == update.message.from_user.id]
    rules_for_all = [rule for rule in rules_with_same_text if rule['from'] == 0]
    
    if len(rules_with_same_user_id) > 0:
        random_rule = random.choice(rules_with_same_user_id)
        await update.message.reply_text(random_rule['response'])
        return
    
    if len(rules_for_all) > 0:
        random_rule = random.choice(rules_for_all)
        await update.message.reply_text(random_rule['response'])
        return   
            
                
            
async def add_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        try:
            from_user, text, response = update.message.text.strip().replace('/add_rule', '').split('|')
            id = uuid.uuid4().hex
            db['rules'].append({'id': id, 'from': int(from_user), 'text': text, 'response': response})
            open('db.json', 'w').write(json.dumps(db, indent=2))
            await update.message.reply_markdown(f'Правило добавлено c id `{id}`')
        except ValueError:
            await update.message.reply_text('Ошибка. Правило должно быть строкой, разделенной "|" например: (0|Привет|Привет)')
            return

async def delete_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        try:
            rule_id = update.message.text.strip().replace('/delete_rule', '')
            db['rules'] = [rule for rule in db['rules'] if rule['id'] != rule_id]
            open('db.json', 'w').write(json.dumps(db, indent=2))
            await update.message.reply_markdown('Правило удалено')
        except ValueError:
            await update.message.reply_text('Ошибка. Id правила должен быть числом')
            return

async def get_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        string = 'Правила: \n\n'
        for rule in db['rules']:
            string += f'id: {rule["id"]} \nОт: {rule["from"]} \nТекст: {rule["text"]} \nОтвет: {rule["response"]} \n\n'
        await update.message.reply_text(text=string)
    
    

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        try:
            admin_id = int(update.message.text.strip().replace('/add_admin', ''))
            db['AdminIds'].append(admin_id)
            open('db.json', 'w').write(json.dumps(db, indent=2))
        except ValueError:
            await update.message.reply_text('Ошибка. Id пользователя должен быть числом')
        
async def delete_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        try:
            admin_id = int(update.message.text.strip().replace('/delete_admin', ''))
            db['AdminIds'].remove(admin_id)
            open('db.json', 'w').write(json.dumps(db, indent=2))
        except ValueError:
            await update.message.reply_text('Ошибка. Id пользователя должен быть числом')



async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    string = 'Список команд: \n\n'\
        '/add_rule - добавить правило в формате (id|Текст|Ответ) \n'\
        '/delete_rule - удалить правило по id \n'\
        '/get_rules - получить все правила \n'\
        '/add_admin - добавить админа в формате (id) \n'\
        '/delete_admin - удалить админа по id \n'\
        '/help - помощь'
    await update.message.reply_text(string)
    


def main():
    application = Application\
        .builder().token(TOKEN)\
        .read_timeout(300).write_timeout(300).pool_timeout(300).connect_timeout(300).media_write_timeout(300)\
        .build()
    application.add_handler(CommandHandler('add_rule', add_rule))
    application.add_handler(CommandHandler('delete_rule', delete_rule))
    application.add_handler(CommandHandler('get_rules', get_rules))
    application.add_handler(CommandHandler('add_admin', add_admin))
    application.add_handler(CommandHandler('delete_admin', delete_admin))
    application.add_handler(CommandHandler('help', help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()