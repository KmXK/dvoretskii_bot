from steward.data.repository import Repository
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler(
    "delete_admin",
    only_admin=True,
    arguments_template=r"(?P<admin_id>\d+)",
    arguments_mapping={
        "admin_id": lambda x: int(x) if x is not None else 0
    },  # TODO: как-нибудь различать обязательные и нет параметры, чтобы избавиться от таких костылей
)
class DeleteAdminHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context, admin_id: int):
        try:
            self.repository.db.admin_ids.remove(admin_id)
            await self.repository.save()
            await update.message.reply_markdown(f"Админ с id={admin_id} удалён")
        except KeyError:
            await update.message.reply_text("Ошибка. Админа с таким id не существует")
        except IndexError:
            await update.message.reply_text("Ошибка. Укажите id админа")

    def help(self):
        return "/delete_admin <id> - удалить админа"
