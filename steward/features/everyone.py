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
        "«призови всех на встречу завтра» → /everyone встреча завтра в 18:00",
    ]
    custom_help = "/everyone [текст] - призвать всех в чате"
    custom_prompt = (
        "▶ /everyone [текст] — призвать всех в чате\n"
        "  Примеры:\n"
        "  - «позови всех» → /everyone\n"
        "  - «призови всех на встречу» → /everyone встреча завтра в 18:00"
    )

    @on_message
    async def everyone(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not ctx.message.text:
            return False
        text = ctx.message.text
        extra = ""
        for prefix in ("/everyone", "@everyone"):
            if text.startswith(prefix):
                extra = text[len(prefix):].strip()
                break
        else:
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
        if extra:
            body += f" {extra}"
        await ctx.message.reply_markdown(body)
        return True
