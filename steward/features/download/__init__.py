import logging
import re

from steward.features.download.transcribe import make_transcribation
from steward.features.download.yt import (
    DOWNLOAD_TYPE_MAP,
    URL_REGEX,
    YT_LIMIT,
    build_dispatch,
)
from steward.framework import (
    Feature,
    FeatureContext,
    on_callback,
    on_message,
)
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger("download_controller")


class DownloadFeature(Feature):
    excluded_from_ai_router = True

    @on_message
    async def on_url(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not ctx.message.text:
            return False
        urls = re.findall(URL_REGEX, ctx.message.text)
        if not urls:
            return False

        dispatch = build_dispatch(self.repository)
        handled = False
        for url in urls:
            for handler_path, handlers in dispatch.items():
                if handler_path not in url:
                    continue
                check_limit(YT_LIMIT, 15, Duration.MINUTE)
                logger.info(f"Получен url: {url}")
                success = False
                for handler in handlers:
                    try:
                        await handler(url, ctx.message)
                        success = True
                        break
                    except Exception as e:
                        logger.exception(e)
                if success:
                    download_type = DOWNLOAD_TYPE_MAP.get(handler_path, handler_path)
                    ctx.metrics.inc(
                        "bot_downloads_total",
                        {"download_type": download_type},
                    )
                handled = True
                break
        return handled

    @on_callback("download:trans", schema="<url:str>")
    async def on_transcribe(self, ctx: FeatureContext, url: str):
        if ctx.callback_query is None or ctx.callback_query.message is None:
            return
        try:
            await make_transcribation(self.repository, ctx.callback_query.message, url)
        except Exception as e:
            logger.exception(e)
