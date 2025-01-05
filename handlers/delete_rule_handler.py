from repository import Repository
from handlers.handler import CommandHandler, Handler


@CommandHandler('delete_rule', only_admin=True)
class DeleteRuleHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            rule_id = update.message.text.split()[1]
            self.repository.delete_rule(rule_id)
            await update.message.reply_markdown('Правило удалено')
        except ValueError:
            await update.message.reply_text('Ошибка. Id правила должен быть числом')
        except IndexError:
            await update.message.reply_text('Ошибка. Укажите Id правила')

    def help(self):
        return '/delete_rule - удалить правило по id'
