import logging

from steward.features.download.transcribe import make_transcribation
from steward.features.download.yt import (
    DOWNLOAD_TYPE_MAP,
    YT_LIMIT,
    build_dispatch,
    find_download_urls,
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
        found = find_download_urls(ctx.message.text)
        if not found:
            return False

        dispatch = build_dispatch(self.repository)
        for url, handler_path in found:
            check_limit(YT_LIMIT, 15, Duration.MINUTE)
            logger.info(f"Получен url: {url}")
            success = False
            for handler in dispatch[handler_path]:
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
        return True

    @on_callback("download:trans", schema="<url:str>")
    async def on_transcribe(self, ctx: FeatureContext, url: str):
        if ctx.callback_query is None or ctx.callback_query.message is None:
            return
        try:
            await make_transcribation(self.repository, ctx.callback_query.message, url)
        except Exception as e:
            logger.exception(e)
