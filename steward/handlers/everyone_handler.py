import random

from steward.handlers.handler import Handler


def get_user_name(user):
    if user.username:
        return user.username

    if random.randint(1, 10) % 2 == 0:
        return user.first_name

    return "p1d0r4s"


class EveryoneHandler(Handler):
    async def chat(self, context):
        if not context.message.text or not (
            context.message.text.startswith("/everyone")
            or context.message.text.startswith("@everyone")
        ):
            return False

        users = [
            user
            for user in await context.client.get_participants(context.message.chat.id)
            if user.id != context.message.from_user.id and not user.bot
        ]
        await context.message.reply_markdown(
            f"[allo](tg://user?id={users[0].id})"
            + "".join(
                [f"[o](tg://user?id={users[i].id})" for i in range(1, len(users))]
            )
        )

    def help(self):
        return "/everyone - призвать всех в чате"
