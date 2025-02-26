import argparse
import logging

from steward.bot.bot import Bot
from steward.bot.bot_utils import init_handlers
from steward.data.repository import JsonFileStorage, Repository
from steward.handlers.add_admin_handler import AddAdminHandler
from steward.handlers.add_rule_handler import AddRuleHandler
from steward.handlers.army_handler import AddArmyHandler, ArmyHandler, DeleteArmyHandler
from steward.handlers.chat_collect_handler import ChatCollectHandler
from steward.handlers.delete_admin_handler import DeleteAdminHandler
from steward.handlers.delete_rule_handler import DeleteRuleHandler
from steward.handlers.download_handler import DownloadHandler
from steward.handlers.exchange_rates_handler import ExchangeRateHandler
from steward.handlers.feature_request_handler import (
    FeatureRequestEditHandler,
    FeatureRequestViewHandler,
)
from steward.handlers.get_admins_handler import GetAdminsHandler
from steward.handlers.get_rules_handler import GetRulesHandler
from steward.handlers.handler import Handler
from steward.handlers.help_handler import HelpHandler
from steward.handlers.holidays_handler import HolidaysHandler
from steward.handlers.id_handler import IdHandler
from steward.handlers.logs_handler import LogsHandler
from steward.handlers.message_info_handler import MessageInfoHandler
from steward.handlers.pretty_time_handler import PrettyTimeHandler
from steward.handlers.rule_answer_handler import RuleAnswerHandler
from steward.handlers.script_handler import ScriptHandler
from steward.handlers.translate_handler import TranslateHandler
from steward.logging.configure import configure_logging

logger: logging.Logger


def get_token(is_test=False):
    if is_test:
        return "***REMOVED***"
    else:
        return "***REMOVED***"


def get_handlers(log_file: None | str):
    # TODO: Union CRUD handlers to one import
    # TODO: Create bot context for bot
    handlers: list[Handler] = init_handlers(
        [
            ChatCollectHandler,
            DownloadHandler,
            GetRulesHandler,
            AddRuleHandler,
            DeleteRuleHandler,
            GetAdminsHandler,
            AddAdminHandler,
            DeleteAdminHandler,
            AddArmyHandler,
            DeleteArmyHandler,
            ArmyHandler,
            FeatureRequestEditHandler,
            FeatureRequestViewHandler,
            IdHandler,
            PrettyTimeHandler,
            MessageInfoHandler,
            TranslateHandler,
            ExchangeRateHandler,
            HolidaysHandler,
            ScriptHandler(
                "update",
                "./scripts/update.sh",
                "скачать изменения и обновить бота",
            ),
            ScriptHandler(
                "reload",
                "./scripts/reload.sh",
                "перезапустить бота",
            ),
            RuleAnswerHandler,
        ],
    )

    if log_file is not None:
        handlers.append(LogsHandler(log_file))

    handlers.append(HelpHandler(handlers))

    return handlers


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
    parser.add_argument(
        "--debug",
        help="Debug mode",
        action="store_true",
    )
    args = parser.parse_args()
    is_test = not args.prod

    token = get_token(is_test)

    configure_logging(token, args.log_file, args.debug)

    repository = Repository(JsonFileStorage("db.json"))
    handlers = get_handlers(args.log_file)

    Bot(handlers, repository).start(
        token,
        drop_pending_updates=True,
        local_server="http://localhost:8001" if not is_test else None,
    )


# GLOBAL TODOS
# TODO: Добавить возможность выполнять действие бота искусственно (chat, callback) и упростить неявные команды в явные

if __name__ == "__main__":
    main()
