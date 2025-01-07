from math import e
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

import logging

from handlers.army_handler import AddArmyHandler, ArmyHandler, DeleteArmyHandler
from handlers.delete_admin_handler import DeleteAdminHandler
from handlers.add_admin_handler import AddAdminHandler
from handlers.delete_rule_handler import DeleteRuleHandler
from handlers.get_admins_handler import GetAdminsHandler
from handlers.get_rules_handler import GetRulesHandler
from handlers.help_handler import HelpHandler
from handlers.download_handler import DownloadHandler
from handlers.logs_handler import LogsHandler
from handlers.rule_answer_handler import RuleAnswerHandler
from handlers.script_handler import ScriptHandler
from handlers.session_creation_handler import SessionCreationHandler

from repository import JsonFileStorage, Repository

from consts import TOKEN
from logging_filters import ReplaceFilter

test = False

if test:
    LOGGING_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)
    TOKEN = "***REMOVED***"
else:
    LOGGING_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        filename="main.log",
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.INFO,
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

    AddArmyHandler(repository),
    DeleteArmyHandler(repository),
    ArmyHandler(repository),

    LogsHandler('./main.log', repository),

    ScriptHandler('update', './update.sh', 'скачать изменения и обновить бота'),
    ScriptHandler('reload', './reload.sh', 'перезапустить бота'),

    RuleAnswerHandler(repository),
]

handlers.append(HelpHandler(handlers, repository))


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for handler in handlers:
        try:
            if hasattr(handler, "chat") and await handler.chat(update, context) == True:
                return
        except BaseException as e:
            logging.exception(e)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for handler in handlers:
        try:
            if hasattr(handler, "callback") and await handler.callback(update, context):
                await update.callback_query.answer()
                return
        except BaseException as e:
            logging.exception(e)


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
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=test)


if __name__ == "__main__":
    main()
