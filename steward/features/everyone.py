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
        "  [текст] — НЕОБЯЗАТЕЛЬНЫЙ. Подставляй его ТОЛЬКО если пользователь явно\n"
        "  передал сообщение для призыва. Если он просто просит позвать/призвать всех\n"
        "  без конкретного текста — верни голую команду /everyone, ничего не дописывай.\n"
        "  Примеры:\n"
        "  - «позови всех» → /everyone\n"
        "  - «собери всех» → /everyone\n"
        "  - «призови всех в чате» → /everyone\n"
        "  - «призови всех на встречу завтра в 18:00» → /everyone встреча завтра в 18:00"
    )

    @on_message
    async def everyone(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not ctx.message.text:
            return False
        text = ctx.message.text
        extra = ""
        for prefix in ("/everyone", "@everyone"):
            if text.startswith(prefix):
                rest = text[len(prefix):]
                # Команда вида «/everyone@botname» — суффикс-меншн бота сразу за
                # командой (без пробела) не часть текста, отрезаем его.
                if rest.startswith("@"):
                    parts = rest.split(None, 1)
                    rest = parts[1] if len(parts) > 1 else ""
                extra = rest.strip()
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
