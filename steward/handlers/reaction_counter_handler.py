from steward.bot.context import ReactionBotContext
from steward.handlers.handler import Handler
from steward.helpers.reactions import get_reactions_info


class ReactionCounterHandler(Handler):
    async def reaction(self, context: ReactionBotContext):
        info = await get_reactions_info(context)

        # if info.added or info.removed:
        #     reply_text = "Reactions updated:\n"
        #     if len(info.added) > 0:
        #         reply_text += f"Added: {' '.join(info.added)}\n"
        #     if len(info.removed) > 0:
        #         reply_text += f"Removed: {' '.join(info.removed)}\n"

        #     await context.bot.send_message(
        #         chat_id=context.message_reaction.chat.id,
        #         text=reply_text,
        #     )
