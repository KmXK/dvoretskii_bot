from steward.data.repository import Repository
from steward.handlers.handler import CommandHandler, Handler


@CommandHandler("add_admin", only_admin=True)
class AddAdminHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            admin_id = int(update.message.text.split()[1])
            self.repository.db.admin_ids.add(admin_id)
            await self.repository.save()
            await update.message.reply_markdown("Админ добавлен")
        except ValueError:
            await update.message.reply_text(
                "Ошибка. id админа должно быть целым числом"
            )
        except IndexError:
            await update.message.reply_text("Ошибка. Укажите id админа")

    def help(self):
        return "/add_admin <id> - добавить админа по id"
