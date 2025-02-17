from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler


@CommandHandler(
    "add_admin",
    only_admin=True,
    arguments_template=r"(?P<id>\d+)",
    arguments_mapping={"id": required(int)},
)
class AddAdminHandler(Handler):
    async def chat(self, context: ChatBotContext, id: int):
        if self.repository.is_admin(id):
            await context.message.reply_text("Такой админ уже есть")
        else:
            self.repository.db.admin_ids.add(id)
            await self.repository.save()
            await context.message.reply_markdown(f"Админ с id = {id} добавлен")

    def help(self):
        return "/add_admin <id> - добавить админа по id"
