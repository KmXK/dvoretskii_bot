from repository import Repository
from handlers.handler import CommandHandler, Handler


@CommandHandler('add_admin', only_admin=True)
class AddAdminHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            admin_id = int(update.message.text.split()[1])
            self.repository.add_admin(admin_id)
            await update.message.reply_markdown('Админ добавлен')
        except ValueError:
            await update.message.reply_text('Ошибка. Id пользователя должен быть числом')
        except IndexError:
            await update.message.reply_text('Ошибка. Укажите Id пользователя')

    def help(self):
        return '/add_admin - добавить админа по id'
