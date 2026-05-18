import logging

from telegram import ReactionTypeEmoji

from steward.framework import Feature, FeatureContext, on_message

logger = logging.getLogger(__name__)

_BOT_USERNAME = "highcast23bot"
_SENT_TEXT = "✅ Отправлено!"


class HighcastCleanupFeature(Feature):
    @on_message
    async def cleanup_sent(self, ctx: FeatureContext) -> bool:
        msg = ctx.message
        if msg is None:
            return False
        sender = msg.from_user
        if sender is None or sender.username != _BOT_USERNAME:
            return False
        if (msg.text or "").strip() != _SENT_TEXT:
            return False
        reply = msg.reply_to_message
        if reply is None:
            return False

        try:
            await ctx.bot.set_message_reaction(
                chat_id=ctx.chat_id,
                message_id=reply.message_id,
                reaction=[ReactionTypeEmoji(emoji="✅")],
            )
        except Exception as e:
            logger.warning("Failed to set reaction: %s", e)

        try:
            await msg.delete()
        except Exception as e:
            logger.warning("Failed to delete highcast sent message: %s", e)

        return True
