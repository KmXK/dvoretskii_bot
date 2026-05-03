from steward.framework import Feature, FeatureContext, ask_message, subcommand, wizard
from steward.helpers.tg_update_helpers import get_message


class MessageInfoFeature(Feature):
    command = "debug_msg"
    description = "Дебаг-инфо о сообщении"

    @subcommand("", description="Запустить дебаг-сессию")
    async def start(self, ctx: FeatureContext):
        await self.start_wizard("debug_msg:run", ctx)

    @wizard(
        "debug_msg:run",
        ask_message(
            "msg",
            "Пришли мне сообщение, чтобы увидеть дебаг инфу",
            filter=lambda m: m is not None,
            error="Некорректное сообщение, попробуй другое",
        ),
    )
    async def on_done(self, ctx: FeatureContext, msg):
        message = get_message(ctx.update)
        await message.chat.send_message(f"```\n{str(msg)}```", parse_mode="markdown")
