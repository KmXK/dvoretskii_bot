from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.webapp import get_webapp_keyboard


class MiniAppFeature(Feature):
    command = "app"
    description = "Открыть мини-приложение"

    @subcommand("", description="Открыть webapp")
    async def open_app(self, ctx: FeatureContext):
        if ctx.message is None:
            return
        keyboard = get_webapp_keyboard(
            ctx.bot,
            ctx.chat_id,
            is_private=ctx.message.chat.type == "private",
        )
        await ctx.message.reply_text("📱 Мини-приложение", reply_markup=keyboard)
