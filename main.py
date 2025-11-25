import argparse
import logging
import os

from dotenv import load_dotenv

from steward.bot.bot import Bot
from steward.bot.bot_utils import init_handlers
from steward.data.repository import JsonFileStorage, Repository
from steward.handlers.add_admin_handler import AddAdminHandler
from steward.handlers.add_rule_handler import AddRuleHandler
from steward.handlers.ai_handler import AIHandler
from steward.handlers.army_handler import AddArmyHandler, ArmyHandler, DeleteArmyHandler
from steward.handlers.chat_collect_handler import ChatCollectHandler
from steward.handlers.db_handler import DbHandler
from steward.handlers.delete_admin_handler import DeleteAdminHandler
from steward.handlers.delete_rule_handler import DeleteRuleHandler
from steward.handlers.download_handler import DownloadHandler
from steward.handlers.everyone_handler import EveryoneHandler
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
from steward.handlers.multiply_handler import MultiplyHandler
from steward.handlers.pasha_handler import (
    PashaHandler,
    PashaRelatedMessageHandler,
    PashaSessionHandler,
)
from steward.handlers.pretty_time_handler import PrettyTimeHandler
from steward.handlers.reaction_counter_handler import ReactionCounterHandler
from steward.handlers.rule_answer_handler import RuleAnswerHandler
from steward.handlers.silence_handler import (
    SilenceCommandHandler,
    SilenceEnforcerHandler,
)
from steward.handlers.subscribe_handler import (
    SubscribeHandler,
    SubscribeRemoveHandler,
    SubscribeViewHandler,
)
from steward.handlers.translate_handler import TranslateHandler
from steward.handlers.voice_video_handler import VoiceVideoHandler
from steward.logging.configure import configure_logging

logger: logging.Logger


def get_handlers(log_file: None | str):
    # TODO: Union CRUD handlers to one import
    # TODO: Create bot context for bot
    handlers: list[Handler] = init_handlers(
        [
            ChatCollectHandler,
            SilenceCommandHandler,
            SilenceEnforcerHandler,
            PashaRelatedMessageHandler,
            DownloadHandler,
            GetRulesHandler,
            AddRuleHandler,
            DeleteRuleHandler,
            ReactionCounterHandler,
            GetAdminsHandler,
            AddAdminHandler,
            DeleteAdminHandler,
            DbHandler,
            AddArmyHandler,
            DeleteArmyHandler,
            ArmyHandler,
            FeatureRequestEditHandler,
            FeatureRequestViewHandler,
            IdHandler,
            PrettyTimeHandler,
            MessageInfoHandler,
            SubscribeRemoveHandler,
            SubscribeViewHandler,
            SubscribeHandler,
            TranslateHandler,
            ExchangeRateHandler,
            HolidaysHandler,
            EveryoneHandler,
            PashaHandler,
            PashaSessionHandler,
            AIHandler,
            RuleAnswerHandler,
            VoiceVideoHandler,
            MultiplyHandler,
        ],
    )

    if log_file is not None:
        handlers.append(LogsHandler(log_file))

    handlers.append(HelpHandler(handlers))

    return handlers


def main():
    load_dotenv()

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

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    assert token

    configure_logging(token, args.log_file, args.debug, args.prod)

    repository = Repository(JsonFileStorage("db.json"))
    handlers = get_handlers(args.log_file)

    Bot(handlers, repository).start(
        token,
        drop_pending_updates=True,
        local_server=os.environ.get("TELEGRAM_API_HOST") if not is_test else None,
    )


# GLOBAL TODOS
# TODO: Добавить возможность выполнять действие бота искусственно (chat, callback) и упростить неявные команды в явные
# TODO: Удалить .* из регулярных выражений, для этого давай сразу edit правил сделаем

if __name__ == "__main__":
    main()
