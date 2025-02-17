from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler("delete_rule", only_admin=True)
class DeleteRuleHandler(Handler):
    async def chat(self, context):
        try:
            rules = context.message.text.split()[1:]

            for rule_id in rules:
                try:
                    self.repository.db.rules.remove(
                        next(
                            (x for x in self.repository.db.rules if x.id == rule_id),
                            None,  # type: ignore (validates in except)
                        )
                    )
                    await self.repository.save()
                    await context.message.reply_markdown(f"Правило {rule_id} удалено")
                except ValueError:
                    await context.message.reply_text(
                        f"Ошибка. Правила с id={rule_id} не существует"
                    )
        except IndexError:
            await context.message.reply_text("Ошибка. Укажите id правил(а)")

    def help(self):
        return "/delete_rule <id> [<id>...] - удалить правило(а)"
