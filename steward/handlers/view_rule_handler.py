from steward.data.repository import Repository
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler


@CommandHandler(
    "rule",
    only_admin=True,
    arguments_template=r"(?P<id>\d+)",
    arguments_mapping={
        "id": required(int),
    },
)
class GetRulesHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context, id: int):
        rule = next((x for x in self.repository.db.rules if x.id == id), None)

        if rule is None:
            await update.message.reply_text("Правила с таким id не существует")
            return True

    def help(self):
        return "/rule <id> - просмотреть правило по id"
