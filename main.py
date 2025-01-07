from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

import logging

from handlers.delete_admin_handler import DeleteAdminHandler
from handlers.add_admin_handler import AddAdminHandler
from handlers.delete_rule_handler import DeleteRuleHandler
from handlers.get_admins_handler import GetAdminsHandler
from handlers.get_rules_handler import GetRulesHandler
from handlers.help_handler import HelpHandler
from handlers.download_handler import DownloadHandler
from handlers.rule_answer_handler import RuleAnswerHandler
from handlers.script_handler import ScriptHandler
from handlers.session_creation_handler import SessionCreationHandler

from repository import JsonFileStorage, Repository

from consts import TOKEN
from logging_filters import ReplaceFilter

test = True

if test:
    LOGGING_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)
    TOKEN = "***REMOVED***"
else:
    LOGGING_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        filename="main.log",
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.WARNING,
    )
    TOKEN = "***REMOVED***"

# logging.getLogger().addFilter(StringFilter('200 OK'))
logger = logging.getLogger(__name__)  # logger for current application

# censor token in logs
logging.getLogger("httpx").addFilter(ReplaceFilter(TOKEN, "<censored token>"))


repository = Repository(JsonFileStorage("db.json"))

handlers = [
    SessionCreationHandler(repository),
    DownloadHandler(),

    GetRulesHandler(repository),
    DeleteRuleHandler(repository),

    GetAdminsHandler(repository),
    AddAdminHandler(repository),
    DeleteAdminHandler(repository),

    ScriptHandler('update', './update.sh', 'скачать изменения и обновить бота'),
    ScriptHandler('reload', './reload.sh', 'перезапустить бота'),

    RuleAnswerHandler(repository),
]

handlers.append(HelpHandler(handlers, repository))


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for handler in handlers:
        if hasattr(handler, "chat") and await handler.chat(update, context) == True:
            return


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for handler in handlers:
        if hasattr(handler, "callback") and await handler.callback(update, context):
            await update.callback_query.answer()
            return


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


def main():
    application = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(300)
        .write_timeout(300)
        .pool_timeout(300)
        .connect_timeout(300)
        .media_write_timeout(300)
        .build()
    )

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


if __name__ == "__main__":
    main()
