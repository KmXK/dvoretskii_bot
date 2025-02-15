from steward.data.repository import Repository
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler("rule", only_admin=True)
class GetRulesHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        rule = next(
            (x for x in self.repository.db.rules if x.id == update.message.id), None
        )

    def help(self):
        return "/rule <id> - просмотреть правило по id"
