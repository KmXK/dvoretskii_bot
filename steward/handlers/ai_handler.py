from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.ai import JAILBREAK_PROMPT, make_deepseek_query


@CommandHandler("ai")
class AIHandler(Handler):
    async def chat(self, context):
        await context.message.reply_markdown(
            make_deepseek_query(
                context.message.from_user.id,
                context.message.text,
                JAILBREAK_PROMPT,
            ),
        )

    def help(self):
        return "/ai - поговорить с ии"
