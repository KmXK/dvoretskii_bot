import argparse
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
from handlers.handler import Handler
from handlers.help_handler import HelpHandler
from handlers.download_handler import DownloadHandler
from handlers.logs_handler import LogsHandler
from handlers.rule_answer_handler import RuleAnswerHandler
from handlers.script_handler import ScriptHandler
from handlers.session_creation_handler import SessionCreationHandler

from repository import JsonFileStorage, Repository

from consts import TOKEN
from logging_filters import ReplaceFilter, SkipFilter


logger: logging.Logger


def configure_logging(is_test, token):
    if is_test:
        log_file_path = None
    else:
        log_file_path = "main.log"

    logging.basicConfig(
        filename=log_file_path,
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    for filter in [
        ReplaceFilter(token, "<censored token>"),
        *[
            SkipFilter(f"/{path} HTTP/1.1 200 OK")
            for path in [
                "getUpdates",
                "getMe",
                "deleteWebhook",
            ]
        ],
    ]:
        logging.getLogger("httpx").addFilter(filter)

    global logger
    logger = logging.getLogger(__name__)  # logger for current application


def get_token(is_test=False):
    if is_test:
        return "***REMOVED***"
    else:
        return "***REMOVED***"


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
    LogsHandler("./main.log", repository),
    ScriptHandler("update", "./update.sh", "скачать изменения и обновить бота"),
    ScriptHandler("reload", "./reload.sh", "перезапустить бота"),
    RuleAnswerHandler(repository),
]

handlers.append(HelpHandler(handlers, repository))


def validate_admin(handler: Handler, update: Update):
    return not handler.only_for_admin or repository.is_admin(
        update.message.from_user.id
    )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for handler in handlers:
        try:
            if (
                validate_admin(handler, update)
                and hasattr(handler, "chat")
                and await handler.chat(update, context) == True
            ):
                return
        except BaseException as e:
            logging.exception(e)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for handler in handlers:
        try:
            if (
                validate_admin(handler, update)
                and hasattr(handler, "callback")
                and await handler.callback(update, context)
            ):
                await update.callback_query.answer()
                return
        except BaseException as e:
            logging.exception(e)


def start_bot(token, drop_pending_updates):
    application = (
        Application.builder()
        .token(token)
        .read_timeout(300)
        .write_timeout(300)
        .pool_timeout(300)
        .connect_timeout(300)
        .media_write_timeout(300)
        .build()
    )

    application.add_handler(MessageHandler(filters.ALL, chat))
    application.add_handler(CallbackQueryHandler(callback))
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=drop_pending_updates,
    )


def main():
    parser = argparse.ArgumentParser("bot")
    parser.add_argument(
        "--prod",
        help="Use production environment",
        action="store_true",
    )
    args = parser.parse_args()
    is_test = not args.prod

    token = get_token(is_test)
    print(args)
    configure_logging(is_test, token)
    start_bot(token, True)


if __name__ == "__main__":
    main()
