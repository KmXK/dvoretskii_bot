import logging

from pyrate_limiter import BucketFullException

from steward.features.download.transcribe import make_transcribation
from steward.features.download.yt import (
    DOWNLOAD_TYPE_MAP,
    YT_LIMIT,
    YandexMusicDownloadError,
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
from steward.helpers.video_trim import create_trimmed_audio_reply, create_trimmed_video_reply, parse_trim_range, range_from_link_message

logger = logging.getLogger("download_controller")

_AI_TRIGGERS = ("дворецкий", "уважаемый")


class DownloadFeature(Feature):
    excluded_from_ai_router = True

    @on_message
    async def on_trim(self, ctx: FeatureContext) -> bool:
        message = ctx.message
        if message is None or not message.text:
            return False

        reply = message.reply_to_message
        if reply is None or (reply.video is None and reply.audio is None):
            return False

        sender = reply.from_user
        via_bot = reply.via_bot
        if not (
            (sender is not None and sender.id == ctx.bot.id)
            or (via_bot is not None and via_bot.id == ctx.bot.id)
        ):
            return False

        time_range = parse_trim_range(message.text)
        if time_range is None:
            return False

        try:
            check_limit(YT_LIMIT, 15, Duration.MINUTE)
            if reply.video is not None:
                await create_trimmed_video_reply(ctx.bot, ctx.client, message, reply, *time_range)
            else:
                await create_trimmed_audio_reply(ctx.bot, message, reply, *time_range)
        except BucketFullException:
            await ctx.reply("Слишком много запросов на видео. Попробуй через минуту.", markdown=False)
        except ValueError as error:
            await ctx.reply(str(error), markdown=False)
        except Exception:
            logger.exception("Media trim failed")
            kind = "видео" if reply.video is not None else "аудио"
            await ctx.reply(f"Не удалось обрезать {kind}. Попробуй ещё раз.", markdown=False)

        return True

    @on_message
    async def on_url(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not ctx.message.text:
            return False
        text = ctx.message.text
        text_lower = text.lower()
        bot_username = ctx.bot.username
        if bot_username and text_lower.startswith(f"@{bot_username.lower()}"):
            return False
        if any(text_lower.startswith(t) for t in _AI_TRIGGERS):
            return False
        found = find_download_urls(text)
        if not found:
            return False

        dispatch = build_dispatch(self.repository)
        for url, handler_path in found:
            try:
                range_from_link_message(ctx.message, url)
            except ValueError as error:
                await ctx.reply(str(error), markdown=False)
                continue
            check_limit(YT_LIMIT, 15, Duration.MINUTE)
            logger.info(f"Получен url: {url}")
            success = False
            error_reported = False
            trim_error = None
            for handler in dispatch[handler_path]:
                try:
                    await handler(url, ctx.message)
                    success = True
                    break
                except YandexMusicDownloadError as error:
                    logger.warning("Yandex Music download failed: %s", error)
                    await ctx.reply(str(error), markdown=False)
                    error_reported = True
                    break
                except ValueError as error:
                    if handler_path == "music.yandex":
                        await ctx.reply(str(error), markdown=False)
                        error_reported = True
                        break
                    if range_from_link_message(ctx.message, url) is not None:
                        trim_error = str(error)
                    else:
                        logger.exception(error)
                    continue
                except Exception as e:
                    logger.exception(e)
            if not success and not error_reported and range_from_link_message(ctx.message, url) is not None:
                await ctx.reply(trim_error or "Не удалось скачать и обрезать медиа. Попробуй ещё раз.", markdown=False)
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
