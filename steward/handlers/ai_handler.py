from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.ai import GROK_SHORT_AGGRESSIVE, OpenRouterModel, make_openrouter_query
from steward.helpers.ai_context import execute_ai_request, register_ai_handler

register_ai_handler(
    "ai",
    lambda uid, msgs: make_openrouter_query(
        uid, OpenRouterModel.GROK_4_FAST, msgs, GROK_SHORT_AGGRESSIVE
    ),
)


@CommandHandler("ai")
class AIHandler(Handler):
    async def chat(self, context: ChatBotContext):
        await execute_ai_request(
            context,
            context.message.text,
            lambda uid, msgs: make_openrouter_query(
                uid, OpenRouterModel.GROK_4_FAST, msgs, GROK_SHORT_AGGRESSIVE
            ),
            "ai",
        )
        return True

    def help(self):
        return "/ai - поговорить с ии"
