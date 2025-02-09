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
    MessageHandler,
    filters,
)

from steward.bot.inline_hints_updater import InlineHintsUpdater
from steward.data.repository import Repository
from steward.handlers.handler import Handler
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

    def start(self, token, drop_pending_updates, local_server: str | None = None):
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
                .local_mode(local_server is not None)
            )

        application = applicationBuilder.build()

        application.add_handler(MessageHandler(filters.ALL, self._chat))
        application.add_handler(CallbackQueryHandler(self._callback))

        async def post_init(*_):
            await self.repository.migrate()
            await self.hints_updater.start(application.bot)

        application.post_init = post_init

        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=drop_pending_updates,
            close_loop=False,
        )

    # TODO: создать контекст для всего запроса, поместить туда контекст тг, update и репозиторий, начать оперировать им
    # (RequestContext!!!)
    async def _chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return False  # dont react on changes

        await self._action(
            update,
            context,
            "chat",
            None,
        )

    async def _callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query is None:
            logger.warning(f"invalid callback call: {update}")
            return False

        await self._action(
            update, context, "callback", lambda: update.callback_query.answer()
        )

    async def _action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        func: Callable[[], Awaitable[Any]] | None,
    ):
        session_handler = try_get_session_handler(update)
        if session_handler is not None:
            if await getattr(session_handler, action)(update, context):
                if func is not None:
                    await func()
                return

        for handler in self.handlers:
            logging.debug(f"Try handler {handler}")
            try:
                if (
                    self._validate_admin(handler, get_from_user(update).id)
                    and hasattr(handler, action)
                    and await getattr(handler, action)(update, context)
                ):
                    logging.debug(f"Used handler {handler}")
                    if func is not None:
                        await func()
                    break
            except BucketFullException as e:
                logging.warning(f"Rate limit exceeded: {e} {update.message}")
                if update.effective_message:
                    await update.effective_message.reply_text("Слишком много запросов")
            except BaseException as e:
                logging.exception(e)

    def _validate_admin(self, handler: Handler, user_id: int):
        return not handler.only_for_admin or self.repository.is_admin(user_id)
