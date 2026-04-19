from dataclasses import dataclass

from telegram import (
    CallbackQuery,
    Message,
    MessageReactionUpdated,
    Update,
)
from telegram.ext import ContextTypes, ExtBot
from telethon import TelegramClient

from steward.bot.context import (
    BotActionContext,
    CallbackBotContext,
    ChatBotContext,
    ReactionBotContext,
)
from steward.data.repository import Repository
from steward.framework.keyboard import Keyboard
from steward.helpers.tg_update_helpers import get_from_user, get_message
from steward.metrics.base import ContextMetrics


@dataclass
class FeatureContext:
    update: Update
    tg_context: ContextTypes.DEFAULT_TYPE
    repository: Repository
    bot: ExtBot[None]
    client: TelegramClient
    metrics: ContextMetrics

    message: Message | None = None
    callback_query: CallbackQuery | None = None
    reaction: MessageReactionUpdated | None = None

    @property
    def message_reaction(self) -> MessageReactionUpdated | None:
        return self.reaction

    @property
    def chat_id(self) -> int:
        return get_message(self.update).chat.id

    @property
    def user_id(self) -> int:
        user = get_from_user(self.update)
        return user.id

    @property
    def username(self) -> str | None:
        user = get_from_user(self.update)
        return user.username

    @property
    def is_callback(self) -> bool:
        return self.callback_query is not None

    async def reply(
        self,
        text: str,
        *,
        keyboard: Keyboard | None = None,
        html: bool = False,
        markdown: bool = True,
        reply_to_message_id: int | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> Message | None:
        markup = keyboard.to_markup() if keyboard is not None else None
        parse_mode: str | None = None
        if html:
            parse_mode = "HTML"
        elif markdown:
            parse_mode = "Markdown"

        target = self.message
        if target is None and self.callback_query is not None:
            target = self.callback_query.message
        if target is None:
            return None

        return await target.reply_text(
            text=text,
            reply_markup=markup,
            parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=disable_web_page_preview,
        )

    async def edit(
        self,
        text: str | None = None,
        *,
        keyboard: Keyboard | None = None,
        html: bool = False,
        markdown: bool = True,
    ) -> None:
        if self.callback_query is None or self.callback_query.message is None:
            return
        markup = keyboard.to_markup() if keyboard is not None else None
        parse_mode: str | None = None
        if html:
            parse_mode = "HTML"
        elif markdown:
            parse_mode = "Markdown"

        if text is None:
            await self.callback_query.edit_message_reply_markup(reply_markup=markup)
        else:
            await self.callback_query.edit_message_text(
                text=text,
                reply_markup=markup,
                parse_mode=parse_mode,
            )

    async def toast(self, text: str | None = None, *, alert: bool = False) -> None:
        if self.callback_query is None:
            return
        await self.callback_query.answer(text=text, show_alert=alert)

    async def delete_or_clear_keyboard(self) -> None:
        if self.callback_query is None or self.callback_query.message is None:
            return
        try:
            await self.callback_query.message.delete()
        except Exception:
            try:
                await self.callback_query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

    async def send_to(
        self,
        chat_id: int,
        text: str,
        *,
        keyboard: Keyboard | None = None,
        html: bool = False,
        markdown: bool = True,
    ) -> Message:
        markup = keyboard.to_markup() if keyboard is not None else None
        parse_mode: str | None = None
        if html:
            parse_mode = "HTML"
        elif markdown:
            parse_mode = "Markdown"
        return await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode=parse_mode,
        )


def from_chat_context(ctx: ChatBotContext) -> FeatureContext:
    return FeatureContext(
        update=ctx.update,
        tg_context=ctx.tg_context,
        repository=ctx.repository,
        bot=ctx.bot,
        client=ctx.client,
        metrics=ctx.metrics,
        message=ctx.message,
    )


def from_callback_context(ctx: CallbackBotContext) -> FeatureContext:
    return FeatureContext(
        update=ctx.update,
        tg_context=ctx.tg_context,
        repository=ctx.repository,
        bot=ctx.bot,
        client=ctx.client,
        metrics=ctx.metrics,
        callback_query=ctx.callback_query,
    )


def from_reaction_context(ctx: ReactionBotContext) -> FeatureContext:
    return FeatureContext(
        update=ctx.update,
        tg_context=ctx.tg_context,
        repository=ctx.repository,
        bot=ctx.bot,
        client=ctx.client,
        metrics=ctx.metrics,
        reaction=ctx.message_reaction,
    )


def from_action_context(ctx: BotActionContext) -> FeatureContext:
    if isinstance(ctx, ChatBotContext):
        return from_chat_context(ctx)
    if isinstance(ctx, CallbackBotContext):
        return from_callback_context(ctx)
    if isinstance(ctx, ReactionBotContext):
        return from_reaction_context(ctx)
    raise TypeError(f"Unknown context type: {type(ctx).__name__}")
