from telegram import InputFile

from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler("db", only_admin=True)
class DbHandler(Handler):
    TARGET_CHAT_ID = -4517560449

    async def chat(self, context: ChatBotContext):
        # Проверяем, что команда вызвана в нужном чате
        if context.message.chat_id != self.TARGET_CHAT_ID:
            return False

        # Отправляем файл db.json в чат
        try:
            with open("db.json", "rb") as db_file:
                await context.bot.send_document(
                    chat_id=self.TARGET_CHAT_ID,
                    document=InputFile(db_file, filename="db.json")
                )
            await context.message.reply_text("Файл db.json отправлен")
        except FileNotFoundError:
            await context.message.reply_text("Файл db.json не найден")
        except Exception as e:
            await context.message.reply_text(f"Ошибка при отправке файла: {e}")

        return True

    def help(self):
        return "/db - отправить файл db.json"

