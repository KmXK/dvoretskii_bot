from telegram import MessageOriginUser

from steward.framework import Feature, FeatureContext, ask_message, subcommand, wizard
from steward.helpers.tg_update_helpers import get_message


class IdFeature(Feature):
    command = "id"
    only_admin = True
    description = "Получить айди пользователя"

    @subcommand("", description="Бесконечный режим")
    async def infinite(self, ctx: FeatureContext):
        await self.start_wizard("id:loop", ctx, repeat=-1, current=0)

    @subcommand("<n:int>", description="Повторить N раз")
    async def repeat(self, ctx: FeatureContext, n: int):
        if n <= 0:
            return
        await self.start_wizard("id:loop", ctx, repeat=n, current=0)

    @wizard(
        "id:loop",
        ask_message(
            "msg",
            "Пришли мне сообщение, чтобы узнать айди автора",
            filter=lambda m: m is not None and isinstance(m.forward_origin, MessageOriginUser),
            error="Некорректное сообщение, попробуй другое",
            transform=lambda m: m.forward_origin.sender_user,
        ),
    )
    async def on_done(self, ctx: FeatureContext, msg, repeat: int, current: int):
        message = get_message(ctx.update)
        await message.chat.send_message(f"Id пользователя {msg.name} = {msg.id}")
        current += 1
        if repeat == -1 or current < repeat:
            await self.start_wizard("id:loop", ctx, repeat=repeat, current=current)
