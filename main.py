import argparse
import logging
import os

from dotenv import load_dotenv

from steward.bot.bot import Bot
from steward.data.repository import JsonFileStorage, Repository
from steward.features._special.ai_router import AiRouterHandler
from steward.features._special.help import HelpFeature
from steward.features.logs import LogsFeature
from steward.features.registry import all_features
from steward.handlers.handler import Handler
from steward.logging.configure import configure_logging
from steward.metrics import MetricsEngine, NoopMetricsEngine, PrometheusMetricsEngine

logger: logging.Logger


def get_handlers(log_file: str | None) -> list[Handler]:
    handlers: list[Handler] = all_features()
    if log_file is not None:
        handlers.append(LogsFeature(log_file))
    handlers.append(AiRouterHandler(handlers))
    handlers.append(HelpFeature(handlers))
    return handlers


def main():
    load_dotenv()

    parser = argparse.ArgumentParser("bot")
    parser.add_argument("--prod", help="Use production environment", action="store_true")
    parser.add_argument("--log-file", help="Log to file")
    parser.add_argument("--debug", help="Debug mode", action="store_true")
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


if __name__ == "__main__":
    main()
