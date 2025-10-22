from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.ai import PASHA_PROMPT, AIModels, make_ai_query


@CommandHandler("pasha", only_admin=True)
class PashaHandler(Handler):
    async def chat(self, context):
        await context.message.reply_text(
            await make_ai_query(
                AIModels.YANDEXGPT_5_PRO,
                context.message.text,
                PASHA_PROMPT,
            )
        )

    def help(self):
        return "/pasha - поговорить с ии пашей"
