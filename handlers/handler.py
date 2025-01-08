from functools import wraps
from typing import Optional
from telegram import MessageEntity, Update
from repository import Repository
from telegram.ext import ContextTypes


class Handler:
    # аккуратно с атрибутом класса, сделал его как значение по умолчанию
    # выносить в конструктор не хочу, чтобы не вызывать super везде
    # но при присвоении значения в дочерних объектах, они создают новый атрибут,
    # а не перезаписывают его тут
    only_for_admin = False

    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Chat message handler"""
        return False

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Callback handler"""
        return False

    def help(self):
        return ''


# проверяет, что в запросе содержится команда к боту
def validate_command_msg(update: Update, command: str) -> bool:
    # скопировал из исходником CommandHandler для модуля телеграма
    # проверяет корректность имени команды
    # в форматах /command и /command@bot
    if isinstance(update, Update) and update.effective_message:
        message = update.effective_message

        if (
            message.entities
            and message.entities[0].type == MessageEntity.BOT_COMMAND
            and message.entities[0].offset == 0
            and message.text
            and message.get_bot()
        ):
            # делит по делителю @ и потом смотрит, что второй элемент массива содержит
            # корректное имя бота: работает как раз в двух форматах
            # (если имя бота там было, то сравнивает его, иначе просто сравнивает две
            #  одинаковые строки)
            messageCommand = message.text[1 : message.entities[0].length]
            command_parts = messageCommand.split("@")
            command_parts.append(message.get_bot().username)

            if not (
                command_parts[0].lower() == command
                and command_parts[1].lower() == message.get_bot().username.lower()
            ):
                return False # команда не подходит для данного хэндлера

            return True
    return False # не зашли в один из первых двух ифов

def validate_admin(update: Update, repository: Repository):
    return repository.is_admin(update.message.from_user.id)

# decorator for simple command handlers
def CommandHandler(command: Optional[str] = None, only_admin: Optional[bool] = None):
    def decorator(handlerClass):
        chat = handlerClass.chat

        @wraps(handlerClass.chat)
        async def filteredChat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            return (
                (command == None or validate_command_msg(update, command))
                and await chat(self, update, context) == True
            )

        handlerClass.only_for_admin = only_admin == True
        handlerClass.chat = filteredChat
        return handlerClass

    return decorator

