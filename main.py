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
from steward.handlers.ai_handler import AIHandler
from steward.handlers.army_handler import (
    ArmyAddHandler,
    ArmyRemoveHandler,
    ArmyViewHandler,
)
from steward.handlers.bill_handler import (
    BillAddHandler,
    BillCloseHandler,
    BillDetailsAddHandler,
    BillDetailsEditHandler,
    BillHelpHandler,
    BillListViewHandler,
    BillMainReportHandler,
    BillPayForceDeleteHandler,
    BillPayHandler,
    BillReportHandler,
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
from steward.handlers.google_drive_handler import GoogleDriveListHandler
from steward.handlers.handler import Handler
from steward.handlers.help_handler import HelpHandler
from steward.handlers.holidays_handler import HolidaysHandler
from steward.handlers.id_handler import IdHandler
from steward.handlers.link_handler import LinkHandler
from steward.handlers.logs_handler import LogsHandler
from steward.handlers.me_handler import MeHandler
from steward.handlers.message_info_handler import MessageInfoHandler
from steward.handlers.miniapp_handler import MiniAppHandler
from steward.handlers.newtext_handler import NewTextHandler
from steward.handlers.multiply_handler import MultiplyHandler
from steward.handlers.ai_related_handler import AiRelatedMessageHandler
from steward.handlers.pasha_handler import (
    PashaHandler,
    PashaSessionHandler,
)
from steward.handlers.pretty_time_handler import PrettyTimeHandler
from steward.handlers.react_handler import ReactHandler
from steward.handlers.reaction_counter_handler import ReactionCounterHandler
from steward.handlers.remind_handler import (
    RemindAddHandler,
    RemindEditHandler,
    RemindersHandler,
    RemindRemoveHandler,
)
from steward.handlers.reward_handler import (
    RewardAddHandler,
    RewardListHandler,
    RewardPresentHandler,
    RewardRemoveHandler,
    RewardTakeHandler,
)
from steward.handlers.rule_answer_handler import RuleAnswerHandler
from steward.handlers.rule_handler import (
    RuleAddHandler,
    RuleListViewHandler,
    RuleRemoveHandler,
    RuleViewHandler,
)
from steward.handlers.silence_handler import (
    SilenceCommandHandler,
    SilenceEnforcerHandler,
)
from steward.handlers.stats_handler import StatsHandler
from steward.handlers.subscribe_handler import (
    SubscribeHandler,
    SubscribeRemoveHandler,
    SubscribeViewHandler,
)
from steward.handlers.tarot_handler import TarotHandler
from steward.handlers.timezone_handler import TimezoneHandler
from steward.handlers.todo_handler import (
    TodoAddHandler,
    TodoDoneHandler,
    TodoListHandler,
    TodoRemoveHandler,
)
from steward.handlers.translate_handler import TranslateHandler
from steward.handlers.voice_video_handler import VoiceVideoHandler
from steward.handlers.watch_handler import WatchHandler
from steward.logging.configure import configure_logging
from steward.metrics import MetricsEngine, NoopMetricsEngine, PrometheusMetricsEngine

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
            AiRelatedMessageHandler,
            RuleListViewHandler,
            RuleViewHandler,
            RuleAddHandler,
            RuleRemoveHandler,
            ReactHandler,
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
            MeHandler,
            RewardListHandler,
            RewardAddHandler,
            RewardRemoveHandler,
            RewardPresentHandler,
            RewardTakeHandler,
            TodoDoneHandler,
            TodoRemoveHandler,
            TodoListHandler,
            TodoAddHandler,
            IdHandler,
            PrettyTimeHandler,
            MessageInfoHandler,
            NewTextHandler,
            SubscribeRemoveHandler,
            SubscribeViewHandler,
            SubscribeHandler,
            TranslateHandler,
            TarotHandler,
            ExchangeRateHandler,
            LinkHandler,
            RemindRemoveHandler,
            RemindEditHandler,
            RemindAddHandler,
            RemindersHandler,
            TimezoneHandler,
            HolidaysHandler,
            EveryoneHandler,
            PashaHandler,
            PashaSessionHandler,
            AIHandler,
            VoiceVideoHandler,
            MultiplyHandler,
            WatchHandler,
            DownloadHandler,
            BillMainReportHandler,
            BillListViewHandler,
            BillAddHandler,
            BillReportHandler,
            BillPayForceDeleteHandler,
            BillPayHandler,
            BillCloseHandler,
            BillDetailsAddHandler,
            BillDetailsEditHandler,
            BillHelpHandler,
            GoogleDriveListHandler,
            StatsHandler,

            RuleAnswerHandler,
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

    metrics_engine: MetricsEngine
    if os.environ.get("METRICS_ENABLED") == "true":
        metrics_port = int(os.environ.get("METRICS_PORT", "9090"))
        vm_url = os.environ.get("VICTORIAMETRICS_URL", "http://victoriametrics:8428")
        metrics_engine = PrometheusMetricsEngine(vm_url=vm_url)
        metrics_engine.start_server(metrics_port)
        logging.info(f"Metrics server started on port {metrics_port}")
    else:
        metrics_engine = NoopMetricsEngine()

    Bot(handlers, repository, metrics_engine).start(
        token,
        drop_pending_updates=True,
        local_server=os.environ.get("TELEGRAM_API_HOST") if not is_test else None,
    )


# GLOBAL TODOS
# TODO: Добавить возможность выполнять действие бота искусственно (chat, callback) и упростить неявные команды в явные
# TODO: Удалить .* из регулярных выражений, для этого давай сразу edit правил сделаем

if __name__ == "__main__":
    main()
