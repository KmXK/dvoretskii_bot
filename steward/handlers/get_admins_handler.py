from steward.data.repository import Repository
from steward.handlers.handler import CommandHandler, Handler


@CommandHandler("get_admins", only_admin=True)
class GetAdminsHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        await update.message.reply_text(
            text="\n".join([
                "Админы:",
                "",
                *[str(i) for i in self.repository.db.admin_ids],
            ])
        )

    def help(self):
        return "/get_admins - получить всех админов"
