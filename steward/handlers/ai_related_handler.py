from steward.bot.context import ChatBotContext
from steward.handlers.handler import Handler
from steward.helpers.ai_context import execute_ai_request, get_ai_handler


class AiRelatedMessageHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if (
            not context.message
            or not context.message.text
            or not context.message.reply_to_message
        ):
            return False

        key = f"{context.message.chat.id}_{context.message.reply_to_message.id}"
        if key not in context.repository.db.ai_messages:
            return False

        ai_message = context.repository.db.ai_messages[key]
        ai_call = get_ai_handler(ai_message.handler)
        if not ai_call:
            return False

        await execute_ai_request(
            context,
            context.message.text,
            ai_call,
            ai_message.handler,
        )
        return True
