import textwrap
from repository import Repository
from handlers.handler import CommandHandler, Handler


@CommandHandler('get_rules', only_admin=True)
class GetRulesHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        strings = ['Правила:', '']
        for rule in self.repository.rules:
            strings.append(textwrap.dedent(f'''\
                    id: {rule['id']}
                    От: {', '.join([str(i) for i in rule['from_users']])}
                    Текст: {rule['pattern']}
                    Количество ответов: {len(rule["responses"])}
                    Игнорировать регистр: {rule["ignore_case_flag"]}
            '''))
        await update.message.reply_text(text='\n'.join(strings))

    def help(self):
        return '/get_rules - просмотреть существующие правила'
