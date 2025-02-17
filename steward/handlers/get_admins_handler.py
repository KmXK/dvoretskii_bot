from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler("get_admins", only_admin=True)
class GetAdminsHandler(Handler):
    async def chat(self, context):
        await context.message.reply_text(
            text="\n".join([
                "Админы:",
                "",
                *[str(i) for i in self.repository.db.admin_ids],
            ])
        )

    def help(self):
        return "/get_admins - получить всех админов"
