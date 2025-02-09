import logging

import coloredlogs

from steward.logging.logging_filters import ReplaceFilter


def configure_logging(token, log_file: None | str):
    coloredlogs.install(
        fmt="%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s",
        level=logging.INFO,
        stream=open(log_file, "a") if log_file else None,
        isatty=log_file is None,
    )

    # TODO: Remove logs /getUpdates (но не удалять другие!!!)
    for filter in [
        ReplaceFilter(token, "<censored token>"),
        #    *[
        #       SkipFilter(f"/{path} HTTP/1.1 200 OK")
        #      for path in [
        #         "getUpdates",
        # "getMe",
        #    "deleteWebhook",
        #            ]
        #        ],
    ]:
        logging.getLogger("httpx").addFilter(filter)

    global logger
    logger = logging.getLogger(__name__)  # logger for current application
