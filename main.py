import json
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

import logging

from handlers.delete_admin_handler import DeleteAdminHandler
from handlers.add_admin_handler import AddAdminHandler
from handlers.delete_rule_handler import DeleteRuleHandler
from handlers.get_admins_handler import GetAdminsHandler
from handlers.get_rules_handler import GetRulesHandler
from handlers.help_handler import HelpHandler
from handlers.download_handler import DownloadHandler
from handlers.session_creation_handler import SessionCreationHandler

from repository import Repository

from consts import TOKEN, URL_REGEX
from logging_filters import ReplaceFilter, StringFilter

test = True

if (test):
    LOGGING_FORMAT='%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)
    TOKEN = '***REMOVED***'
else:
    LOGGING_FORMAT='%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig( filename='main.log', format='%(asctime)s - %(levelname)s - %(message)s', level=logging.WARNING)
    TOKEN = '***REMOVED***'

# logging.getLogger().addFilter(StringFilter('200 OK'))
logger = logging.getLogger(__name__) # logger for current application

# censor token in logs
logging.getLogger('httpx').addFilter(ReplaceFilter(TOKEN, '<censored token>'))


repository = Repository()

handlers = [
    SessionCreationHandler(repository),
    DownloadHandler(),
    GetRulesHandler(repository),
    DeleteRuleHandler(repository),
    GetAdminsHandler(repository),
    AddAdminHandler(repository),
    DeleteAdminHandler(repository),
]

handlers.append(HelpHandler(handlers, repository))


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for handler in handlers:
        if hasattr(handler, 'chat') and await handler.chat(update, context):
            return

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for handler in handlers:
        if hasattr(handler, 'callback') and await handler.callback(update, context):
            await update.callback_query.answer()
            return


# async def response_on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

#     if (update.message.text is None):
#         return


#     rules_with_same_text = [rule for rule in repository.rules if re.match(rule['text'], update.message.text, re.IGNORECASE if rule['case_flag'] == 1 else 0)]
#     rules_with_same_user_id = [rule for rule in rules_with_same_text if rule['from'] == update.message.from_user.id]
#     rules_for_all = [rule for rule in rules_with_same_text if rule['from'] == 0]

#     if len(rules_with_same_user_id) > 0:
#         random_rule = random.choice(rules_with_same_user_id)
#         await update.message.reply_text(random_rule['response'])
#         return

#     if len(rules_for_all) > 0:
#         random_rule = random.choice(rules_for_all)
#         await update.message.reply_text(random_rule['response'])
#         return


#         try:
#             from_user, text, response, case_flag = update.message.text.strip().replace('/add_rule', '').split('%')
#             id = uuid.uuid4().hex
#             repository.add_rule(Rule(id, from_user, text, response, case_flag))
#             await update.message.reply_markdown(f'Правило добавлено c id `{id}`')
#         except ValueError:
#             string = 'Ошибка. Правило должно быть строкой, разделенной "%" например: (0%Привет%Привет%0) \n' \
#                 'from - id пользователя, которому принадлежит правило, если 0 - для всех \n' \
#                 'text - текст правила \n' \
#                 'response - ответ на правило \n' \
#                 'case_flag - 1 - регистр не учитывается, 0 - регистр учитывается'
#             await update.message.reply_text(text=string)
#             return

# async def delete_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if (repository.is_admin(update.message.from_user.id)):
#         try:
#             rule_id = update.message.text.strip().replace('/delete_rule', '').strip()
#             repository.delete_rule(rule_id)
#             await update.message.reply_markdown('Правило удалено')
#         except ValueError:
#             await update.message.reply_text('Ошибка. Id правила должен быть числом')
#             return

# async def get_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if (repository.is_admin(update.message.from_user.id)):
#         string = 'Правила: \n\n'
#         for rule in repository.rules:
#             string += f'id: {rule["id"]} \nОт: {rule["from"]} \nТекст: {rule["text"]} \nОтвет: {rule["response"]} \nИгнорировать регистр: {rule["case_flag"]} \n\n'
#         await update.message.reply_text(text=string)
    
    

# async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if (repository.is_admin(update.message.from_user.id)):
#         try:
#             admin_id = int(update.message.text.strip().replace('/add_admin', ''))
#             repository.add_admin(admin_id)
#         except ValueError:
#             await update.message.reply_text('Ошибка. Id пользователя должен быть числом')
        
# async def delete_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if (repository.is_admin(update.message.from_user.id)):
#         try:
#             admin_id = int(update.message.text.strip().replace('/delete_admin', ''))
#             repository.delete_admin(admin_id)
#         except ValueError:
#             await update.message.reply_text('Ошибка. Id пользователя должен быть числом')

# async def get_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if (repository.is_admin(update.message.from_user.id)):
#         string = 'Админы: \n\n'
#         for admin_id in repository.admin_ids:
#             string += f'{admin_id} \n'
#         await update.message.reply_text(text=string)



# PAGE_SIZE = 25
# def get_keyboard(start_item: int) -> InlineKeyboardMarkup:
#     log_len = len(open('main.log').readlines())
#     keyboard = [
#         [
#             InlineKeyboardButton('<<<', callback_data=f'logs_page|0'),
#             InlineKeyboardButton('<', callback_data=f'logs_page|{start_item - PAGE_SIZE if start_item - PAGE_SIZE > 0 else 0}'),
#             InlineKeyboardButton('>', callback_data=f'logs_page|{start_item + PAGE_SIZE if start_item + PAGE_SIZE < log_len else log_len - PAGE_SIZE}'),
#             InlineKeyboardButton('>>>', callback_data=f'logs_page|{log_len - PAGE_SIZE}'),
#         ]
#     ]
#     reply_markup = InlineKeyboardMarkup(keyboard)
#     return reply_markup

# async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     reply_markup = get_keyboard(0)
#     with open('main.log') as f:
#         lines = f.readlines()[-PAGE_SIZE:]
#         await update.message.reply_text(''.join(lines), reply_markup=reply_markup)

# async def show_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     start_item = int(update.callback_query.data.split('|')[1])
#     reply_markup = get_keyboard(start_item)
#     await update.callback_query.edit_message_text(open('main.log').readlines()[start_item:start_item + PAGE_SIZE], reply_markup=reply_markup)
#     await update.callback_query.answer()



# async def reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if os.path.exists('script.sh'):
#         process = await asyncio.create_subprocess_shell('sudo ./script.sh', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
#         await process.communicate()



# async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     string = 'Список команд: \n\n'\
#         '/add_rule - добавить правило в формате (id%Текст%Ответ%Игнорировать ли регистр) \n'\
#         '/delete_rule - удалить правило по id \n'\
#         '/add_admin - добавить админа в формате (id) \n'\
#         '/delete_admin - удалить админа по id \n'\
#         '/get_admins - получить всех админов \n'\
#         '/logs - получить логи \n' \
#         '/reload - перезагрузить бота \n' \
#         '/help - помощь'
#     await update.message.reply_text(string)



def main():
    application = Application.builder()\
        .token(TOKEN)\
        .read_timeout(300)\
        .write_timeout(300)\
        .pool_timeout(300)\
        .connect_timeout(300)\
        .media_write_timeout(300)\
        .build()

    application.add_handler(MessageHandler(filters.ALL, chat))
    application.add_handler(CallbackQueryHandler(callback))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


    # application.add_handler(CommandHandler('delete_rule', delete_rule))
    # application.add_handler(CommandHandler('get_rules', get_rules))
    # application.add_handler(CommandHandler('add_admin', add_admin))
    # application.add_handler(CommandHandler('delete_admin', delete_admin))
    # application.add_handler(CommandHandler('get_admins', get_admins))
    # application.add_handler(CommandHandler('logs', show_logs))
    # application.add_handler(CommandHandler('reload', reload))
    # application.add_handler(CallbackQueryHandler(show_logs_callback))
    # application.add_handler(CommandHandler('help', help))




if __name__ == '__main__':
    main()
