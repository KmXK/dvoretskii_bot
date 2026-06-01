import asyncio
import logging
from os import environ
from typing import Any, Awaitable, Callable

from pyrate_limiter import BucketFullException
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    ExtBot,
    InlineQueryHandler,
    MessageHandler,
    MessageReactionHandler,
    filters,
)
from telethon import TelegramClient

from steward.bot.context import (
    BotActionContext,
    CallbackBotContext,
    ChatBotContext,
    ReactionBotContext,
)
from steward.birthday_checker import BirthdayChecker
from steward.joke_checker import JokeChecker
from steward.api.server import start_api_server
from steward.bot.delayed_action_handler import DelayedActionHandler
from steward.dynamic_rewards import DynamicRewardChecker, ensure_dynamic_rewards_exist
from steward.bot.inline_hints_updater import InlineHintsUpdater
from steward.data.repository import Repository
from steward.handlers.handler import Handler
from steward.helpers.command_validation import ValidationArgumentsError
from steward.helpers.curse_debt import initialize_curse_debts, today_msk
from steward.helpers.tg_update_helpers import UnsupportedUpdateType, get_from_user
from steward.helpers.webapp import get_webapp_inline_button
from steward.metrics import ContextMetrics, MetricsEngine
from steward.session.session_registry import (
    cleanup_stale_sessions,
    deactivate_session,
    try_get_session_handler,
)

logger = logging.getLogger(__name__)


async def _safe_post_action(func: Callable[[], Awaitable[Any]]) -> None:
    try:
        await func()
    except BadRequest as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            return
        raise


class Bot:
    def __init__(
        self,
        handlers: list[Handler],
        repository: Repository,
        metrics: MetricsEngine,
    ):
        self.handlers = handlers
        self.repository = repository
        self.metrics = metrics

        self.hints_updater = InlineHintsUpdater(repository, handlers)
        self.session_ttl_seconds = int(environ.get("SESSION_TTL_SECONDS", "14400"))

        self.bot: ExtBot[None] = None  # type: ignore
        self.delayed_action_handler: DelayedActionHandler

        for handler in handlers:
            handler.repository = repository
            handler._all_handlers = handlers

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

        from steward.bot.message_splitter import patch_send_message
        patch_send_message()

        application = applicationBuilder.concurrent_updates(True).build()
        self.bot = application.bot

        for handler in self.handlers:
            handler.bot = self.bot

        application.add_handler(MessageHandler(filters.ALL, self._chat, block=False))
        application.add_handler(MessageReactionHandler(self._chat, block=False))
        application.add_handler(CallbackQueryHandler(self._callback, block=False))
        application.add_handler(InlineQueryHandler(self._inline_query, block=False))
        application.add_handler(
            ChatMemberHandler(self._my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER, block=False)
        )

        async def post_init(*_):
            await self.repository.migrate()
            await self.hints_updater.start(application.bot)

            if await initialize_curse_debts(self.repository, self.metrics, today_msk()):
                await self.repository.save()

            from steward.features.fuck import migrate_legacy_fuck_assets
            if migrate_legacy_fuck_assets(self.repository):
                await self.repository.save()

            if ensure_dynamic_rewards_exist(self.repository):
                await self.repository.save()

            for handler in self.handlers:
                if init_coro := handler.init():  # type: ignore
                    await init_coro

        application.post_init = post_init

        self.client = TelegramClient(
            ".steward_session",
            api_id=int(environ.get("TELEGRAM_API_ID", "")),
            api_hash=environ.get("TELEGRAM_API_HASH", ""),
        )
        self.client.start(bot_token=environ.get("TELEGRAM_BOT_TOKEN", ""))

        with self.client:
            self.delayed_action_handler = DelayedActionHandler(
                self.repository,
                self.bot,
                self.client,
                self.metrics,
            )
            asyncio.ensure_future(self.delayed_action_handler.start())

            self.birthday_checker = BirthdayChecker(self.repository, self.bot)
            asyncio.ensure_future(self.birthday_checker.start())

            self.dynamic_reward_checker = DynamicRewardChecker(self.repository, self.metrics)
            asyncio.ensure_future(self.dynamic_reward_checker.start())

            self.joke_checker = JokeChecker(self.repository, self.bot, self.client)
            asyncio.ensure_future(self.joke_checker.start())

            api_port = int(environ.get("API_PORT", "8080"))
            asyncio.ensure_future(
                start_api_server(self.repository, self.metrics, api_port, self.bot, self.handlers)
            )

            application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=drop_pending_updates,
                close_loop=False,
            )

    def _empty_metrics(self) -> ContextMetrics:
        return ContextMetrics(self.metrics, {})

    async def _inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.inline_query
        if query is None:
            return

        button = get_webapp_inline_button()
        await query.answer([], button=button, cache_time=300)

    async def _chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logging.info("Got update")
        if update.message is not None:
            ctx = ChatBotContext(
                self.repository,
                self.bot,
                self.client,
                update,
                context,
                self._empty_metrics(),
                update.message,
            )

            await self._action(
                ctx,
                "chat",
                None,
            )
        elif update.edited_message is not None:
            ctx = ChatBotContext(
                self.repository,
                self.bot,
                self.client,
                update,
                context,
                self._empty_metrics(),
                update.edited_message,
            )
            await self._action(ctx, "message_edited", None)
        elif update.message_reaction:
            ctx = ReactionBotContext(
                self.repository,
                self.bot,
                self.client,
                update,
                context,
                self._empty_metrics(),
                update.message_reaction,
            )

            await self._action(
                ctx,
                "reaction",
                None,
            )
        else:
            return False

    async def _callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query is None:
            logger.warning(f"invalid callback call: {update}")
            return False

        ctx = CallbackBotContext(
            self.repository,
            self.bot,
            self.client,
            update,
            context,
            self._empty_metrics(),
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
        user_id: int | None = None

        stale_count = cleanup_stale_sessions(self.session_ttl_seconds)
        if stale_count > 0:
            logger.info("Cleaned %s stale session(s)", stale_count)

        try:
            user = get_from_user(update)
            chat = update.effective_chat
            chat_id = str(chat.id) if chat else "unknown"
            chat_name = (chat.title or chat.username or chat.first_name or chat_id) if chat else "unknown"
            user_id = user.id if user else None
            user_id_str = str(user_id) if user_id is not None else "unknown"
            user_name = (user.username or user.first_name or user_id_str) if user else "unknown"
            context.metrics = ContextMetrics(self.metrics, {
                "chat_id": chat_id,
                "chat_name": chat_name,
                "user_id": user_id_str,
                "user_name": user_name,
            })
            context.metrics.inc("bot_messages_total", {"action_type": action})
        except UnsupportedUpdateType:
            context.metrics = ContextMetrics(self.metrics, {})

        eff_chat = update.effective_chat
        chat_id_int = eff_chat.id if eff_chat else None

        try:
            session_handler = try_get_session_handler(update) if user_id is not None else None
            if session_handler is not None:
                if not self._validate_admin(session_handler, user_id, chat_id_int):
                    deactivate_session(update)
                    logger.warning("Dropped session for non-admin user %s", user_id)
                elif hasattr(session_handler, action) and await getattr(session_handler, action)(context):
                    if func is not None:
                        await _safe_post_action(func)
                    return
        except UnsupportedUpdateType:
            pass
        except BaseException as e:
            logger.exception(e)

        for handler in self.handlers:
            logging.debug(f"Try handler {handler}")
            try:
                if not self._validate_admin(handler, user_id, chat_id_int):
                    continue
                cap_check = self._capability_check(handler, context, action)
                if cap_check == "skip":
                    continue
                if cap_check == "disabled_reply":
                    await self._reply_capability_disabled(context, handler)
                    break
                if hasattr(handler, action) and await getattr(handler, action)(context):
                    logging.debug(f"Used handler {handler}")
                    self.metrics.inc("bot_handler_calls_total", {"handler": handler.__class__.__name__})
                    if func is not None:
                        await _safe_post_action(func)
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

    def _validate_admin(self, handler: Handler, user_id: int | None, chat_id: int | None = None):
        if handler.only_for_admin:
            return user_id is not None and self.repository.is_admin(user_id)
        if getattr(handler, "only_for_chat_admin", False):
            return (
                user_id is not None
                and chat_id is not None
                and self.repository.is_chat_admin(user_id, chat_id)
            )
        return True

    def _capability_check(
        self,
        handler: Handler,
        context: "BotActionContext",
        action: str,
    ) -> str:
        """Return 'ok' if handler may run, 'skip' to silently bypass,
        or 'disabled_reply' to respond «функция выключена»."""
        from steward.features.registry import is_always_on

        if is_always_on(handler.__class__):
            return "ok"
        chat = context.update.effective_chat
        if chat is None:
            return "ok"
        cap = handler.capability
        if cap is None:
            return "ok"
        if self.repository.is_capability_enabled(chat.id, handler.__class__):
            return "ok"
        # capability is disabled — figure out if this is a slash-command invocation
        if action == "chat":
            msg = context.update.effective_message
            command = getattr(handler, "command", None)
            if command and msg and msg.text:
                from steward.helpers.command_validation import validate_command_msg
                aliases = getattr(handler, "aliases", ()) or ()
                names = [command, *aliases]
                if validate_command_msg(context.update, names):
                    return "disabled_reply"
        return "skip"

    async def _reply_capability_disabled(self, context: "BotActionContext", handler: Handler):
        msg = context.update.effective_message
        if msg is None:
            return
        try:
            await msg.reply_text("Функция выключена в этом чате. /settings")
        except BaseException as e:
            logging.exception(e)

    async def _my_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from steward.data.models.chat_settings import ChatSettings

        cmu = update.my_chat_member
        if cmu is None:
            return
        new = cmu.new_chat_member
        old = cmu.old_chat_member
        bot_joined = (
            new is not None
            and new.status in ("member", "administrator")
            and (old is None or old.status in ("left", "kicked"))
        )
        if not bot_joined:
            return
        chat_id = cmu.chat.id
        adder = cmu.from_user
        adder_id = adder.id if adder else None
        adder_username = adder.username if adder else None

        existing = next(
            (s for s in self.repository.db.chat_settings if s.chat_id == chat_id),
            None,
        )
        if existing is not None:
            return

        settings = ChatSettings(
            chat_id=chat_id,
            enabled_capabilities=set(),
            chat_admins={adder_id} if adder_id else set(),
            onboarded=False,
        )
        self.repository.db.chat_settings.append(settings)
        await self.repository.save()

        who = f"@{adder_username}" if adder_username else "Админ"
        greeting = (
            "Привет! Я выключен по умолчанию.\n"
            f"{who}, ты теперь chat-admin — открой настройки и включи что нужно."
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "⚙ Открыть настройки",
                callback_data=f"settings:root|{chat_id}",
            )
        ]])
        try:
            await self.bot.send_message(chat_id, greeting, reply_markup=kb)
        except BaseException as e:
            logging.exception(e)
