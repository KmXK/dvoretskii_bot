import argparse
import logging
import os

from dotenv import load_dotenv

from steward.bot.bot import Bot
from steward.bot.bot_utils import init_handlers
from steward.data.repository import JsonFileStorage, Repository
from steward.handlers.admin_handler import (
    AdminAddHandler,
    AdminRemoveHandler,
    AdminViewHandler,
)
from steward.handlers.rule_handler import (
    RuleAddHandler,
    RuleListViewHandler,
    RuleRemoveHandler,
    RuleViewHandler,
)
from steward.handlers.ai_handler import AIHandler
from steward.handlers.army_handler import (
    ArmyAddHandler,
    ArmyRemoveHandler,
    ArmyViewHandler,
)
from steward.handlers.chat_collect_handler import ChatCollectHandler
from steward.handlers.db_handler import DbHandler
from steward.handlers.download_handler import DownloadHandler
from steward.handlers.everyone_handler import EveryoneHandler
from steward.handlers.exchange_rates_handler import ExchangeRateHandler
from steward.handlers.feature_request_handler import (
    FeatureRequestEditHandler,
    FeatureRequestViewHandler,
)
from steward.handlers.handler import Handler
from steward.handlers.help_handler import HelpHandler
from steward.handlers.holidays_handler import HolidaysHandler
from steward.handlers.id_handler import IdHandler
from steward.handlers.link_handler import LinkHandler
from steward.handlers.logs_handler import LogsHandler
from steward.handlers.message_info_handler import MessageInfoHandler
from steward.handlers.miniapp_handler import MiniAppHandler
from steward.handlers.multiply_handler import MultiplyHandler
from steward.handlers.pasha_handler import (
    PashaHandler,
    PashaRelatedMessageHandler,
    PashaSessionHandler,
)
from steward.handlers.pretty_time_handler import PrettyTimeHandler
from steward.handlers.reaction_counter_handler import ReactionCounterHandler
from steward.handlers.remind_handler import RemindAddHandler, RemindEditHandler, RemindRemoveHandler, RemindersHandler
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
from steward.handlers.watch_handler import WatchHandler
from steward.logging.configure import configure_logging

logger: logging.Logger


def get_handlers(log_file: None | str):
    # TODO: Union CRUD handlers to one import
    # TODO: Create bot context for bot
    handlers: list[Handler] = init_handlers(
        [
            MiniAppHandler,
            ChatCollectHandler,
            SilenceCommandHandler,
            SilenceEnforcerHandler,
            PashaRelatedMessageHandler,
            RuleListViewHandler,
            RuleViewHandler,
            RuleAddHandler,
            RuleRemoveHandler,
            ReactionCounterHandler,
            AdminViewHandler,
            AdminAddHandler,
            AdminRemoveHandler,
            DbHandler,
            ArmyViewHandler,
            ArmyAddHandler,
            ArmyRemoveHandler,
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
            LinkHandler,
            RemindRemoveHandler,
            RemindEditHandler,
            RemindAddHandler,
            RemindersHandler,
            HolidaysHandler,
            EveryoneHandler,
            PashaHandler,
            PashaSessionHandler,
            AIHandler,
            RuleAnswerHandler,
            VoiceVideoHandler,
            MultiplyHandler,
            WatchHandler,
            DownloadHandler,
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
