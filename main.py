import logging.handlers
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from bs4 import BeautifulSoup
from datetime import datetime

import re, asyncio, aiohttp, os, json, logging, uuid, random

from consts import LOGGING_FORMAT, TOKEN, URL_REGEX
from logging_filters import ReplaceFilter, StringFilter

logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)

# add separate handler (console is still working)
file_handler = logging.FileHandler('temp.log')
file_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
file_handler.addFilter(StringFilter('200 OK')) # dont write logs about successfull http request to file
logging.getLogger().addHandler(file_handler)
logger = logging.getLogger(__name__) # logger for current application

# censor token in logs
logging.getLogger('httpx').addFilter(ReplaceFilter(TOKEN, '<censored token>'))

db =  json.loads(open('db.json').read())


def init_db():
    if not os.path.exists('db.json'):
        with open('db.json', 'w') as f:
            f.write('{"AdminIds": [***REMOVED***, ***REMOVED***], "rules": [], "version": 1, "army": []}')

def migrate_db():
    if db.get('version') is None:
        db['version'] = 1
    if db.get('army') is None:
        db['army'] = []
    open('db.json', 'w').write(json.dumps(db, indent=2))

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db_message_response(update, context)

    urls = re.findall(URL_REGEX, update.message.text)
    for url in urls:
        if 'tiktok' in url:
            try:
                print("Тикток пошел")
                async with aiohttp.ClientSession() as session:
                    logger.info('Запрос на получение информации')

                    async with session.post("https://ttsave.app/download", data={'query': url, 'language_id': "1"}) as response:                             
                        bs = BeautifulSoup(await response.text(), 'html.parser')

                        video = [a.get('href') for a in bs.find_all('a', type="no-watermark") if a.get('href') is not None]
                        if len(video) > 0:
                            logger.info('Видео получено')
                            await update.message.reply_video(video[0])
                            logger.info('Видео отправлено')
                            return

                        images = [InputMediaPhoto(a.get('href')) for a in bs.find_all('a', type="slide") if a.get('href') is not None]        
                        if len(images) > 0:
                            logger.info('Картинки получены')
                            for i in range(0, len(images), 10):
                                await update.message.reply_media_group(images[i:i+10])  
                            logger.info('Картинки отправлены')
                            return

                        await update.message.reply_text("Ты плохой человек")
            except Exception as e:
                logger.exception(e)
            return
            # try:
            #     print("Тикток пошел")
            #     async with aiohttp.ClientSession() as session:
            #         async with session.get("http://8.215.8.243:1337/tiktok?url="+url) as response:                             
            #             json = await response.json()

            #             if not json['status']:
            #                 await update.message.reply_text("Ты плохой человек")

            #             result = json['result']
            #             print(result)

            #             if result.get('video') is not None:
            #                 await update.message.reply_video(result.get('video'))
            #             else:
            #                 print("Картинки пошли")
            #                 images = [InputMediaPhoto(image) for image in result.get('image')]
            #                 if len(images) > 0:
            #                     for i in range(0, len(images), 10):
            #                         await update.message.reply_media_group(images[i:i+10])  

            #                 audio = result.get('audio')
            #                 if audio is not None:
            #                     await update.message.reply_audio(audio)
            # except Exception as e:
            #     logger.exception(e)
            # return

        if 'instagram.com' in url:
            try:
                print("Инстаграм пошел")
                async with aiohttp.ClientSession() as session:
                    async with session.get("http://8.215.8.243:1337/instagram?url="+url) as response:                             
                        json = await response.json()
                        if json['status']:
                            video = json['result'][0]
                            await update.message.reply_video(video)

            except Exception as e:
                logger.exception(e)
            return

        if 'youtube.com' or 'youtu.be' in url:
            try:
                print("Youtube пошел")
                async with aiohttp.ClientSession() as session:
                    async with session.get("http://8.215.8.243:1337/youtube", params={'url': url, 'type': 'video'}) as response:
                        print (await response.text())
                        json = await response.json()
            except Exception as e:
                logger.exception(e)
            return

async def db_message_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules_with_same_text = [rule for rule in db['rules'] if re.match(rule['text'], update.message.text, re.IGNORECASE if rule['case_flag'] == 1 else 0)]
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
            from_user, text, response, case_flag = update.message.text.strip().replace('/add_rule', '').split('%')
            id = uuid.uuid4().hex
            db['rules'].append({'id': id, 'from': int(from_user), 'text': text, 'response': response, 'case_flag': int(case_flag)})
            open('db.json', 'w').write(json.dumps(db, indent=2))
            await update.message.reply_markdown(f'Правило добавлено c id `{id}`')
        except ValueError:
            string = 'Ошибка. Правило должно быть строкой, разделенной "%" например: (0%Привет%Привет%0) \n' \
                'from - id пользователя, которому принадлежит правило, если 0 - для всех \n' \
                'text - текст правила \n' \
                'response - ответ на правило \n' \
                'case_flag - 1 - регистр не учитывается, 0 - регистр учитывается'
            await update.message.reply_text(text=string)
            return

async def delete_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        try:
            rule_id = update.message.text.strip().replace('/delete_rule', '').strip()
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
            string += f'id: {rule["id"]} \nОт: {rule["from"]} \nТекст: {rule["text"]} \nОтвет: {rule["response"]} \nИгнорировать регистр: {rule["case_flag"]} \n\n'
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

async def get_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        string = 'Админы: \n\n'
        for admin_id in db['AdminIds']:
            string += f'{admin_id} \n'
        await update.message.reply_text(text=string)

PAGE_SIZE = 25
def get_keyboard(start_item: int) -> InlineKeyboardMarkup:
    log_len = len(open('main.log').readlines())
    keyboard = [
        [
            InlineKeyboardButton('<<<', callback_data=f'logs_page|0'),
            InlineKeyboardButton('<', callback_data=f'logs_page|{start_item - PAGE_SIZE if start_item - PAGE_SIZE > 0 else 0}'),
            InlineKeyboardButton('>', callback_data=f'logs_page|{start_item + PAGE_SIZE if start_item + PAGE_SIZE < log_len else log_len - PAGE_SIZE}'),
            InlineKeyboardButton('>>>', callback_data=f'logs_page|{log_len - PAGE_SIZE}'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup

async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = get_keyboard(0)
    with open('main.log') as f:
        lines = f.readlines()[-PAGE_SIZE:]
        await update.message.reply_text(''.join(lines), reply_markup=reply_markup)

async def show_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_item = int(update.callback_query.data.split('|')[1])
    reply_markup = get_keyboard(start_item)
    await update.callback_query.edit_message_text(open('main.log').readlines()[start_item:start_item + PAGE_SIZE], reply_markup=reply_markup)
    await update.callback_query.answer()

async def update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in db['AdminIds']:
        logger.info(f"Not admin is trying to update bot: {update.message.from_user}")
        return

    if not os.path.exists('update.sh'):
        logger.info("no update script found")
        return

    logger.info("updating bot sources + reload")
    process = await asyncio.create_subprocess_exec('./update.sh', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    [stdout, stderr] = await process.communicate()

    logger.info(f"Update command result: \nstdout: {stdout.decode()}\nstderr: {stderr.decode()}");

    if process.returncode != 0:
        await update.message.reply_markdown(f'Update script executed with errorcode {process.returncode}')
        return

    await update.message.reply_markdown('Updating has been finished successfully. Reloading...')
    logger.info("Updating has been finished successfully. Reloading...")
    process = await asyncio.create_subprocess_exec('./reload.sh')
    await process.communicate()

async def army(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(db['army']) == 0:
            text += "В армейку никого не добавили"

        text = "Статус по армейке на сегодня: \n\n"
        for army in db['army']:
            day, month, year = army['date'].split('.')
            count_days = (datetime(int(year), int(month), int(day)) - datetime.now()).days
            if count_days > 0:
                text += f"{army['name']} - осталось дней: {count_days}\n"
            else:
                text += f"{army['name']} - дембель\n"
        await update.message.reply_markdown(text)
    except Exception as e:
        print(e)

async def add_army(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        try:
            name, date = update.message.text.strip().replace('/add_army', '').split('%')
            db['army'].append({'name': name.strip(), 'date': date.strip()})
            open('db.json', 'w').write(json.dumps(db, indent=2))
            await update.message.reply_markdown(f'Добавил человечка')
        except ValueError:
            string = 'Ошибка. Добавление должно быть строкой, разделенной "%" например: (Ваня%01.01.2022) \n' \
                'name - Имя \n' \
                'date - дата в формате дд.мм.гггг \n'
            await update.message.reply_text(string)

async def delete_army(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.from_user.id in db['AdminIds']):
        name = update.message.text.strip().replace('/delete_army', '').strip()
        db['army'] = [rule for rule in db['army'] if rule['name'] != name]
        open('db.json', 'w').write(json.dumps(db, indent=2))
        await update.message.reply_markdown('Удалил человечка')

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    string = 'Список команд: \n\n'\
        '/add_rule - добавить правило в формате (id%Текст%Ответ%Игнорировать ли регистр) \n'\
        '/delete_rule - удалить правило по id \n'\
        '/get_rules - получить все правила \n'\
        '/add_admin - добавить админа в формате (id) \n'\
        '/delete_admin - удалить админа по id \n'\
        '/get_admins - получить всех админов \n'\
        '/army - получить статус по армейке \n' \
        '/add_army - добавить человечка в формате (Имя%дата в формате дд.мм.гггг) \n' \
        '/delete_army - удалить человечка по имени \n' \
        '/logs - получить логи \n' \
        '/reload - перезагрузить бота \n' \
        '/help - помощь'
    await update.message.reply_text(string)

def main():
    init_db()
    migrate_db()

    application = Application\
        .builder().token(TOKEN)\
        .read_timeout(300).write_timeout(300).pool_timeout(300).connect_timeout(300).media_write_timeout(300)\
        .build()
    application.add_handler(CommandHandler('add_rule', add_rule))
    application.add_handler(CommandHandler('delete_rule', delete_rule))
    application.add_handler(CommandHandler('get_rules', get_rules))
    application.add_handler(CommandHandler('add_admin', add_admin))
    application.add_handler(CommandHandler('delete_admin', delete_admin))
    application.add_handler(CommandHandler('get_admins', get_admins))
    application.add_handler(CommandHandler('army', army))
    application.add_handler(CommandHandler('add_army', add_army))
    application.add_handler(CommandHandler('delete_army', delete_army))
    application.add_handler(CommandHandler('logs', show_logs))
    application.add_handler(CommandHandler('update', update))
    application.add_handler(CallbackQueryHandler(show_logs_callback))
    application.add_handler(CommandHandler('help', help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
