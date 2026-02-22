from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg


@CommandHandler(
    "admin",
    only_admin=True,
    arguments_template=r"add (?P<id>\d+)",
    arguments_mapping={"id": required(int)},
)
class AdminAddHandler(Handler):
    async def chat(self, context: ChatBotContext, id: int):
        if self.repository.is_admin(id):
            await context.message.reply_text("Такой админ уже есть")
        else:
            self.repository.db.admin_ids.add(id)
            await self.repository.save()
            await context.message.reply_markdown(f"Админ с id = {id} добавлен")

    def help(self):
        return None


@CommandHandler(
    "admin",
    only_admin=True,
    arguments_template=r"remove (?P<id>\d+)",
    arguments_mapping={"id": required(int)},
)
class AdminRemoveHandler(Handler):
    async def chat(self, context: ChatBotContext, id: int):
        try:
            self.repository.db.admin_ids.remove(id)
            await self.repository.save()
            await context.message.reply_markdown(f"Админ с id = {id} удалён")
        except KeyError:
            await context.message.reply_text("Ошибка. Админа с таким id не существует")

    def help(self):
        return None


class AdminViewHandler(Handler):
    only_for_admin = True

    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "admin"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) > 1 and parts[1] in ["add", "remove"]:
            return False

        admin_ids = list(self.repository.db.admin_ids)
        if not admin_ids:
            await context.message.reply_text("Админов нет")
            return True

        await context.message.reply_text(
            text="\n".join([
                "Админы:",
                "",
                *[str(i) for i in admin_ids],
            ])
        )
        return True

    def help(self):
        return "/admin [add <id>|remove <id>] - управлять админами"

    def prompt(self):
        return (
            "▶ /admin — управление админами\n"
            "  Список: /admin\n"
            "  Добавить: /admin add <id>\n"
            "  Удалить: /admin remove <id>"
        )
