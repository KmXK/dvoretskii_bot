from handlers.handler import CommandHandler, Handler
from repository import Repository


@CommandHandler('delete_admin', only_admin=True)
class DeleteAdminHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            admin_id = int(update.message.text.split()[1])
            self.repository.db.admin_ids.remove(admin_id)
            self.repository.save()
            await update.message.reply_markdown('Админ удалён')
        except ValueError:
            await update.message.reply_text('Ошибка. Id админа должно быть целым числом')
        except KeyError:
            await update.message.reply_text('Ошибка. Админа с таким id не существует')
        except IndexError:
            await update.message.reply_text('Ошибка. Укажите id админа')

    def help(self):
        return '/delete_admin - удалить админа по id'
