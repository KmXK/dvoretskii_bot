from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.ai import GROK_SHORT_AGGRESSIVE, OpenRouterModel, make_openrouter_query


@CommandHandler("ai")
class AIHandler(Handler):
    async def chat(self, context):
        await context.message.reply_markdown(
            make_openrouter_query(
                context.message.from_user.id,
                OpenRouterModel.GROK_4_FAST,
                context.message.text,
                GROK_SHORT_AGGRESSIVE,
            ),
        )
        return True

    def help(self):
        return "/ai - поговорить с ии"
