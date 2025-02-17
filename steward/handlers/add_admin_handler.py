from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler("add_admin", only_admin=True)
class AddAdminHandler(Handler):
    async def chat(self, context):
        try:
            admin_id = int(context.message.text.split()[1])
            self.repository.db.admin_ids.add(admin_id)
            await self.repository.save()
            await context.message.reply_markdown("Админ добавлен")
        except ValueError:
            await context.message.reply_text(
                "Ошибка. id админа должно быть целым числом"
            )
        except IndexError:
            await context.message.reply_text("Ошибка. Укажите id админа")

    def help(self):
        return "/add_admin <id> - добавить админа по id"
