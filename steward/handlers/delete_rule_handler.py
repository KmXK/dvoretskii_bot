from handlers.handler import CommandHandler, Handler
from steward.repository import Repository


@CommandHandler("delete_rule", only_admin=True)
class DeleteRuleHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            rules = update.message.text.split()[1:]
            for rule_id in rules:
                try:
                    self.repository.db.rules.remove(
                        next(
                            (x for x in self.repository.db.rules if x.id == rule_id),
                            None,
                        )
                    )
                    self.repository.save()
                    await update.message.reply_markdown(f"Правило {rule_id} удалено")
                except ValueError:
                    await update.message.reply_text(
                        f"Ошибка. Правила с id={rule_id} не существует"
                    )
        except IndexError:
            await update.message.reply_text("Ошибка. Укажите id правил(а)")

    def help(self):
        return "/delete_rule - удалить правило(а) по id через пробел"
