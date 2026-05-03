import logging
from dataclasses import dataclass

from pyrate_limiter import BucketFullException
from telegram import ReactionTypeCustomEmoji, ReactionTypeEmoji

from steward.framework import Feature, FeatureContext, on_reaction, subcommand
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)

MAX_REACT_COUNT = 100
USER_LIMIT = 150
GLOBAL_LIMIT = 500
_GLOBAL_KEY = "react_global"


@dataclass
class _PendingReact:
    bot_msg_id: int
    cmd_msg_id: int
    count: int


class ReactFeature(Feature):
    command = "react"
    description = "Поставить реакции на N последних сообщений"
    help_examples = ["«поставь реакцию на 5 последних сообщений» → /react 5"]

    def __init__(self):
        super().__init__()
        self._pending: dict[tuple[int, int], _PendingReact] = {}

    @subcommand("<n:int>", description="Поставить реакцию")
    async def request(self, ctx: FeatureContext, n: int):
        if n < 1 or n > MAX_REACT_COUNT:
            await ctx.reply(f"Укажите число от 1 до {MAX_REACT_COUNT}")
            return
        reply = await ctx.message.reply_text("Поставь реакцию на это сообщение")
        chat_id = ctx.chat_id
        user_id = ctx.user_id
        self._pending[(chat_id, user_id)] = _PendingReact(
            bot_msg_id=reply.message_id,
            cmd_msg_id=ctx.message.message_id,
            count=n,
        )

    @on_reaction
    async def on_react(self, ctx: FeatureContext) -> bool:
        mr = ctx.reaction
        if mr is None:
            return False
        chat_id = mr.chat.id
        user_id = mr.user.id if mr.user else (mr.actor_chat.id if mr.actor_chat else None)
        if user_id is None:
            return False
        pending = self._pending.get((chat_id, user_id))
        if not pending or mr.message_id != pending.bot_msg_id:
            return False
        new_reactions = mr.new_reaction
        if not new_reactions:
            return False
        del self._pending[(chat_id, user_id)]

        try:
            await ctx.bot.delete_message(chat_id=chat_id, message_id=pending.bot_msg_id)
        except Exception:
            pass

        raw = new_reactions[0]
        reaction = None
        if isinstance(raw, ReactionTypeCustomEmoji):
            try:
                stickers = await ctx.bot.get_custom_emoji_stickers([raw.custom_emoji_id])
                reaction = ReactionTypeEmoji(emoji=stickers[0].emoji) if stickers else None
            except Exception:
                pass
        elif isinstance(raw, ReactionTypeEmoji):
            reaction = raw
        if reaction is None:
            return True

        user_key = f"react_user_{user_id}"
        for i in range(1, pending.count + 1):
            msg_id = pending.cmd_msg_id - i
            try:
                check_limit(user_key, USER_LIMIT, Duration.MINUTE)
                check_limit(_GLOBAL_KEY, GLOBAL_LIMIT, Duration.MINUTE)
            except BucketFullException:
                logger.warning("Rate limit hit, stopping at %d/%d", i - 1, pending.count)
                break
            try:
                try:
                    await ctx.bot.set_message_reaction(
                        chat_id=chat_id, message_id=msg_id, reaction=[],
                    )
                except Exception:
                    pass
                await ctx.bot.set_message_reaction(
                    chat_id=chat_id, message_id=msg_id, reaction=[reaction],
                )
            except Exception as e:
                logger.warning("Failed to set reaction on msg %s: %s", msg_id, e)
        return True
