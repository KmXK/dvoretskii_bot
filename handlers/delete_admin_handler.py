from repository import Repository
from handlers.handler import CommandHandler, Handler


@CommandHandler('delete_admin', only_admin=True)
class DeleteAdminHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            admin_id = int(update.message.text.split()[1])
            self.repository.delete_admin(admin_id)
            await update.message.reply_markdown('Админ удалён')
        except ValueError:
            await update.message.reply_text('Ошибка. Id пользователя должен быть числом')
        except IndexError:
            await update.message.reply_text('Ошибка. Укажите Id пользователя')

    def help(self):
        return '/delete_admin - удалить админа по id'
