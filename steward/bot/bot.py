import logging
from typing import Any, Awaitable, Callable, Optional, TypeGuard

from telegram import (
    BotCommandScope,
    BotCommandScopeChat,
    BotCommandScopeChatMember,
    BotCommandScopeDefault,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    ExtBot,
    MessageHandler,
    filters,
)

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
        self.bot: ExtBot[None] = None  # type: ignore

    def start(self, token, drop_pending_updates):
        application = (
            Application.builder()
            .token(token)
            .read_timeout(300)
            .write_timeout(300)
            .pool_timeout(300)
            .connect_timeout(300)
            .media_write_timeout(300)
            .build()
        )

        application.add_handler(MessageHandler(filters.ALL, self._chat))
        application.add_handler(CallbackQueryHandler(self._callback))

        async def post_init(*_):
            await self.repository.migrate()
            await self._start_bot_commands_hints_update(application.bot)

        application.post_init = post_init

        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=drop_pending_updates,
            close_loop=False,
        )

    # TODO: Call command on chat list update
    async def _start_bot_commands_hints_update(self, bot: ExtBot[None]):
        async def set_commands(
            filter_func: Callable[[Handler], bool],
            scope: BotCommandScope,
        ) -> bool:
            def check_not_null[T](x: Optional[T]) -> TypeGuard[T]:
                return x is not None

            command_texts = [
                *filter(
                    check_not_null, (x.help() for x in self.handlers if filter_func(x))
                )
            ]

            def parse_help_msg(x: str):
                parts = x.split(" ")
                return (parts[0], " ".join(parts[1:]))

            commands = [parse_help_msg(x) for x in command_texts]

            return await bot.set_my_commands(commands, scope)

        chat_ids: set[int] = set()

        async def update_admin_hints():
            if len(chat_ids) == len(self.repository.db.chats):
                return

            new_set = set((x.id for x in self.repository.db.chats if x.id < 0))
            diff = new_set - chat_ids

            chat_ids.update(new_set)

            # TODO: Clear commands for user on admin delete
            # TODO: Add commands to new admin after save (check not only chats changed)
            for chat_id in diff:
                for admin_id in self.repository.db.admin_ids:
                    await set_commands(
                        lambda x: True,
                        BotCommandScopeChatMember(chat_id, admin_id),
                    )

        await update_admin_hints()

        # for admins
        self.repository.subscribe_on_save(update_admin_hints)
        for admin_id in self.repository.db.admin_ids:
            try:
                await set_commands(lambda x: True, BotCommandScopeChat(admin_id))
            except TelegramError:
                pass  # chat can be deleted

        # for all users
        await set_commands(lambda x: not x.only_for_admin, BotCommandScopeDefault())

    # TODO: создать контектс для всего запроса, поместить туда контекст тг, update и репозиторий, начать оперировать им
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
            try:
                if (
                    self._validate_admin(handler, get_from_user(update).id)
                    and hasattr(handler, action)
                    and await getattr(handler, action)(update, context)
                ):
                    if func is not None:
                        await func()
                    break
            except BaseException as e:
                logging.exception(e)

    def _validate_admin(self, handler: Handler, user_id: int):
        return not handler.only_for_admin or self.repository.is_admin(user_id)
