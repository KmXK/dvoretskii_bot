import logging

import coloredlogs

from steward.logging.logging_filters import ReplaceFilter


def configure_logging(
    token,
    log_file: None | str,
    is_debug: bool = False,
    is_prod: bool = False,
):
    if is_prod:
        logging.basicConfig(
            format="%(asctime)s.%(msecs)03d - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s",
            level=logging.DEBUG if is_debug else logging.INFO,
            stream=open(log_file, "a") if log_file else None,
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        coloredlogs.install(
            fmt="%(asctime)s.%(msecs)03d - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s",
            level=logging.DEBUG if is_debug else logging.INFO,
            stream=open(log_file, "a") if log_file else None,
            isatty=log_file is None,
            datefmt="%Y-%m-%d %H:%M:%S",
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
