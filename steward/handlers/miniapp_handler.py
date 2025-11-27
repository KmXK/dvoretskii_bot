import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler("app", only_admin=True)
class MiniAppHandler(Handler):
    async def chat(self, context):
        try:
            # Получаем URL веб-приложения из переменной окружения
            web_url = os.environ.get("WEB_APP_URL", "http://localhost:5173")
            
            # Получаем username бота
            bot_username = context.bot.username
            
            if not bot_username:
                await context.message.reply_text("Не удалось получить имя бота")
                return True
            
            # Формируем ссылку на мини-приложение
            # Формат: https://t.me/{bot_username}/{app_name}
            mini_app_url = f"https://t.me/{bot_username}/app?startapp=webapp"
            
            # Telegram требует HTTPS для Web App кнопок
            # Если URL начинается с http://, используем обычную URL кнопку
            if web_url.startswith("https://"):
                # Создаем кнопку с Web App (только для HTTPS)
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "Открыть приложение",
                        web_app=WebAppInfo(url=web_url)
                    )]
                ])
            else:
                # Для HTTP используем обычную URL кнопку
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "Открыть приложение",
                        url=web_url
                    )]
                ])
            
            await context.message.reply_text(
                f"Открыть мини-приложение:\n{mini_app_url}",
                reply_markup=keyboard
            )
            return True
        except Exception as e:
            logger.exception(f"Error in MiniAppHandler: {e}")
            await context.message.reply_text(f"Ошибка: {str(e)}")
            return True

    def help(self):
        return "/app - получить ссылку на мини-приложение"

