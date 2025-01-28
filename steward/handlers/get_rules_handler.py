import textwrap

from steward.data.repository import Repository
from steward.handlers.handler import CommandHandler, Handler


@CommandHandler("get_rules", only_admin=True)
class GetRulesHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
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
        await update.message.reply_text(text="\n".join(strings))

    def help(self):
        return "/get_rules - просмотреть существующие правила"
