import random

from steward.framework import Feature, FeatureContext, on_message


def _user_name(user) -> str:
    if user.username:
        return user.username
    if random.randint(1, 10) % 2 == 0:
        return user.first_name
    return "p1d0r4s"


class EveryoneFeature(Feature):
    description = "Призвать всех в чате"
    help_examples = [
        "«позови всех» → /everyone",
        "«призови всех в чат» → /everyone",
    ]
    custom_help = "/everyone - призвать всех в чате"
    custom_prompt = (
        "▶ /everyone — призвать всех в чате\n"
        "  Без аргументов: /everyone\n"
        "  Примеры:\n"
        "  - «позови всех» → /everyone\n"
        "  - «призови всех в чат» → /everyone"
    )

    @on_message
    async def everyone(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not ctx.message.text:
            return False
        text = ctx.message.text
        if not (text.startswith("/everyone") or text.startswith("@everyone")):
            return False
        users = [
            user
            for user in await ctx.client.get_participants(ctx.message.chat.id)
            if user.id != ctx.user_id and not user.bot
        ]
        if not users:
            return True
        body = f"[allo](tg://user?id={users[0].id})"
        for u in users[1:]:
            body += f"[o](tg://user?id={u.id})"
        await ctx.message.reply_markdown(body)
        return True
