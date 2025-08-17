import asyncio
import logging
from typing import Any, Awaitable, Callable

from pyrate_limiter import BucketFullException
from telegram import (
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    ExtBot,
    MessageHandler,
    filters,
)

from steward.bot.context import BotActionContext, CallbackBotContext, ChatBotContext
from steward.bot.delayed_action_handler import DelayedActionHandler
from steward.bot.inline_hints_updater import InlineHintsUpdater
from steward.data.repository import Repository
from steward.handlers.handler import Handler
from steward.helpers.command_validation import ValidationArgumentsError
from steward.helpers.tg_update_helpers import get_from_user
from steward.session.session_registry import try_get_session_handler

logger = logging.getLogger(__name__)


class Bot:
    def __init__(
        self,
        handlers: list[Handler],
        repository: Repository,
    ):
        self.handlers = handlers
        self.repository = repository

        self.hints_updater = InlineHintsUpdater(repository, handlers)

        self.bot: ExtBot[None] = None  # type: ignore
        self.delayed_action_handler: DelayedActionHandler

        for handler in handlers:
            handler.repository = repository
            handler.bot = self.bot

    def start(
        self,
        token: str,
        drop_pending_updates: bool,
        local_server: str | None = None,
    ):
        applicationBuilder = (
            Application.builder()
            .token(token)
            .read_timeout(300)
            .write_timeout(300)
            .pool_timeout(300)
            .connect_timeout(300)
            .media_write_timeout(300)
            .local_mode(True)
        )

        if local_server is not None:
            applicationBuilder = (
                applicationBuilder.base_url(local_server + "/bot")
                .base_file_url(local_server + "/file/bot")
                .local_mode(True)
            )

        application = applicationBuilder.concurrent_updates(True).build()

        application.add_handler(MessageHandler(filters.ALL, self._chat, block=False))
        application.add_handler(CallbackQueryHandler(self._callback, block=False))

        async def post_init(*_):
            await self.repository.migrate()
            await self.hints_updater.start(application.bot)

            for handler in self.handlers:
                if init_coro := handler.init():  # type: ignore
                    await init_coro

        application.post_init = post_init

        self.bot = application.bot

        self.delayed_action_handler = DelayedActionHandler(self.repository, self.bot)
        asyncio.ensure_future(
            self.delayed_action_handler.start(),
            loop=asyncio.get_event_loop(),
        )

        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=drop_pending_updates,
            close_loop=False,
        )

    async def _chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return False  # dont react on changes

        ctx = ChatBotContext(
            self.repository,
            self.bot,
            update,
            context,
            update.message,
        )

        await self._action(
            ctx,
            "chat",
            None,
        )

    async def _callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query is None:
            logger.warning(f"invalid callback call: {update}")
            return False

        ctx = CallbackBotContext(
            self.repository,
            self.bot,
            update,
            context,
            update.callback_query,
        )

        await self._action(
            ctx,
            "callback",
            lambda: ctx.callback_query.answer(),
        )

    async def _action(
        self,
        context: BotActionContext,
        action: str,
        func: Callable[[], Awaitable[Any]] | None,
    ):
        update = context.update

        session_handler = try_get_session_handler(update)
        if session_handler is not None:
            if await getattr(session_handler, action)(context):
                if func is not None:
                    await func()
                return

        for handler in self.handlers:
            logging.debug(f"Try handler {handler}")
            try:
                if (
                    self._validate_admin(handler, get_from_user(update).id)
                    and hasattr(handler, action)
                    and await getattr(handler, action)(context)
                ):
                    logging.debug(f"Used handler {handler}")
                    if func is not None:
                        await func()
                    break
            except ValidationArgumentsError as e:
                logging.warning(f"Validation error: {e} {update.message}")
                help_msg = handler.help()
                if update.effective_message and help_msg:
                    await update.effective_message.reply_text(
                        "Использование: " + help_msg
                    )
                    break
            except BucketFullException as e:
                logging.warning(f"Rate limit exceeded: {e} {update.message}")
                if update.effective_message:
                    await update.effective_message.reply_text("Слишком много запросов")
            except BaseException as e:
                logging.exception(e)

    def _validate_admin(self, handler: Handler, user_id: int):
        return not handler.only_for_admin or self.repository.is_admin(user_id)
