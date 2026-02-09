from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.webapp import get_webapp_keyboard


@CommandHandler("app", only_admin=True)
class MiniAppHandler(Handler):
    async def chat(self, context):
        keyboard = get_webapp_keyboard(
            context.bot,
            context.message.chat_id,
            is_private=context.message.chat.type == "private",
        )
        await context.message.reply_text(
            "📱 Мини-приложение",
            reply_markup=keyboard,
        )
        return True

    def help(self):
        return "/app - открыть мини-приложение"
