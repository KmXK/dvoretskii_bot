from repository import Repository
from handlers.handler import CommandHandler, Handler


@CommandHandler('delete_rule', only_admin=True)
class DeleteRuleHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            rule_id = update.message.text.split()[1]
            self.repository.db.rules.remove(next((x for x in self.repository.db.rules if x.id == rule_id), None))
            self.repository.save()
            await update.message.reply_markdown('Правило удалено')
        except ValueError:
            await update.message.reply_text('Ошибка. Правила с таким id не существует')
        except IndexError:
            await update.message.reply_text('Ошибка. Укажите id правила')

    def help(self):
        return '/delete_rule - удалить правило по id'
