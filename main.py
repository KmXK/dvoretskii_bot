import argparse
import logging
from typing import Any, Awaitable, Callable

import coloredlogs
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from handlers.add_admin_handler import AddAdminHandler
from handlers.army_handler import AddArmyHandler, ArmyHandler, DeleteArmyHandler
from handlers.delete_admin_handler import DeleteAdminHandler
from handlers.delete_rule_handler import DeleteRuleHandler
from handlers.download_handler import DownloadHandler
from handlers.feature_request_handler import (
    FeatureRequestEditHandler,
    FeatureRequestViewHandler,
)
from handlers.get_admins_handler import GetAdminsHandler
from handlers.get_rules_handler import GetRulesHandler
from handlers.handler import Handler
from handlers.help_handler import HelpHandler
from handlers.id_handler import IdHandler
from handlers.logs_handler import LogsHandler
from handlers.rule_answer_handler import RuleAnswerHandler
from handlers.script_handler import ScriptHandler
from handlers.session_creation_handler import SessionCreationHandler
from logging_filters import ReplaceFilter, SkipFilter
from repository import JsonFileStorage, Repository
from session.session_registry import try_get_session_handler
from tg_update_helpers import get_from_user, get_message

logger: logging.Logger


def configure_logging(token, log_file: None | str):
    coloredlogs.install(
        fmt="%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s",
        level=logging.INFO,
        stream=open(log_file, "a") if log_file else None,
        isatty=log_file is None,
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
    FeatureRequestEditHandler(repository),
    FeatureRequestViewHandler(repository),
    LogsHandler("./main.log", repository),
    IdHandler(),
    ScriptHandler("update", "./update.sh", "скачать изменения и обновить бота"),
    ScriptHandler("reload", "./reload.sh", "перезапустить бота"),
    RuleAnswerHandler(repository),
]

handlers.append(HelpHandler(handlers, repository))


# TODO: создать контектс для всего запроса, поместить туда контекст тг, update и репозиторий, начать оперировать им
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return False  # dont react on changes

    await action(
        update,
        context,
        "chat",
        None,
    )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await action(update, context, "callback", lambda u: u.callback_query.answer())


def validate_admin(handler: Handler, user_id: int):
    return not handler.only_for_admin or repository.is_admin(user_id)


async def action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    func: Callable[[Update], Awaitable[Any]],
):
    session_handler = try_get_session_handler(get_message(update))
    if session_handler is not None:
        if await getattr(session_handler, action)(update, context):
            if func is not None:
                await func(update)
            return

    for handler in handlers:
        try:
            if (
                validate_admin(handler, get_from_user(update).id)
                and hasattr(handler, action)
                and await getattr(handler, action)(update, context)
            ):
                if func is not None:
                    await func(update)
                break
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
    parser.add_argument(
        "--log-file",
        help="Log to file",
    )
    args = parser.parse_args()
    is_test = not args.prod

    token = get_token(is_test)
    configure_logging(token, args.log_file)
    start_bot(token, True)


if __name__ == "__main__":
    main()
