from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler


@CommandHandler(
    "delete_admin",
    only_admin=True,
    arguments_template=r"(?P<admin_id>\d+)",
    arguments_mapping={"admin_id": required(int)},
)
class DeleteAdminHandler(Handler):
    async def chat(self, context: ChatBotContext, admin_id: int):
        try:
            self.repository.db.admin_ids.remove(admin_id)
            await self.repository.save()
            await context.message.reply_markdown(f"Админ с id={admin_id} удалён")
        except KeyError:
            await context.message.reply_text("Ошибка. Админа с таким id не существует")
        except IndexError:
            await context.message.reply_text("Ошибка. Укажите id админа")

    def help(self):
        return "/delete_admin <id> - удалить админа"
