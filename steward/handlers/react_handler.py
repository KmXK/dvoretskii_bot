import logging
from dataclasses import dataclass

from pyrate_limiter import BucketFullException
from telegram import ReactionTypeCustomEmoji, ReactionTypeEmoji

from steward.bot.context import ChatBotContext, ReactionBotContext
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)

MAX_REACT_COUNT = 100
USER_LIMIT = 150
GLOBAL_LIMIT = 500
_GLOBAL_KEY = "react_global"


@dataclass
class PendingReact:
    bot_msg_id: int
    cmd_msg_id: int
    count: int


class ReactHandler(Handler):
    def __init__(self):
        self._pending: dict[tuple[int, int], PendingReact] = {}

    async def chat(self, context: ChatBotContext) -> bool:
        result = validate_command_msg(context.update, "react", r"(?P<n>\d+)")
        if not result:
            return False

        n = int(result.args["n"])
        if n < 1 or n > MAX_REACT_COUNT:
            await context.message.reply_text(f"Укажите число от 1 до {MAX_REACT_COUNT}")
            return True

        reply = await context.message.reply_text("Поставь реакцию на это сообщение")

        chat_id = context.message.chat_id
        user_id = context.message.from_user.id
        self._pending[(chat_id, user_id)] = PendingReact(
            bot_msg_id=reply.message_id,
            cmd_msg_id=context.message.message_id,
            count=n,
        )
        return True

    async def reaction(self, context: ReactionBotContext) -> bool:
        mr = context.message_reaction
        chat_id = mr.chat.id
        user_id = mr.user.id if mr.user else (mr.actor_chat.id if mr.actor_chat else None)
        logger.info(
            "reaction: chat=%s user=%s msg=%s pending=%s",
            chat_id, user_id, mr.message_id, self._pending,
        )
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
            await context.bot.delete_message(chat_id=chat_id, message_id=pending.bot_msg_id)
        except Exception:
            pass

        raw = new_reactions[0]
        if isinstance(raw, ReactionTypeCustomEmoji):
            try:
                stickers = await context.bot.get_custom_emoji_stickers([raw.custom_emoji_id])
                reaction = ReactionTypeEmoji(emoji=stickers[0].emoji) if stickers else None
            except Exception:
                reaction = None
        elif isinstance(raw, ReactionTypeEmoji):
            reaction = raw
        else:
            reaction = None

        if not reaction:
            return True

        user_key = f"react_user_{user_id}"
        for i in range(1, pending.count + 1):
            msg_id = pending.cmd_msg_id - i
            try:
                check_limit(user_key, USER_LIMIT, Duration.MINUTE)
                check_limit(_GLOBAL_KEY, GLOBAL_LIMIT, Duration.MINUTE)
            except BucketFullException:
                logger.warning("Rate limit hit for react, stopping at %d/%d", i - 1, pending.count)
                break
            try:
                try:
                    await context.bot.set_message_reaction(
                        chat_id=chat_id, message_id=msg_id, reaction=[],
                    )
                except Exception:
                    pass
                await context.bot.set_message_reaction(
                    chat_id=chat_id, message_id=msg_id, reaction=[reaction],
                )
            except Exception as e:
                logger.warning("Failed to set reaction on msg %s: %s", msg_id, e)

        return True

    def help(self):
        return "/react <N> — поставить реакцию на N последних сообщений"
