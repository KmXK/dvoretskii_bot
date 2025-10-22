from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.ai import JAILBREAK_PROMPT, make_deepseek_query


@CommandHandler("ai", only_admin=True)
class AIHandler(Handler):
    async def chat(self, context):
        await context.message.reply_text(
            make_deepseek_query(
                context.message.text,
                JAILBREAK_PROMPT,
            ),
        )

    def help(self):
        return "/ai - поговорить с ии"
