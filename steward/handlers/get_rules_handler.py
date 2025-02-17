import textwrap

from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler("get_rules", only_admin=True)
class GetRulesHandler(Handler):
    async def chat(self, context):
        strings = ["Правила:", ""]
        for rule in self.repository.db.rules:
            strings.append(
                textwrap.dedent(f"""\
                    id: {rule.id}
                    От: {", ".join([str(i) for i in rule.from_users])}
                    Текст: {rule.pattern.regex}
                    Количество ответов: {len(rule.responses)}
                    Игнорировать регистр: {rule.pattern.ignore_case_flag}
            """)
            )
        await context.message.reply_text(text="\n".join(strings))

    def help(self):
        return "/get_rules - просмотреть существующие правила"
