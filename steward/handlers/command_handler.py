import inspect
from functools import wraps

from pyrate_limiter import Optional
from telegram import Update
from telegram.ext import ContextTypes

from steward.helpers.command_validation import validate_command_msg


# проверяет, что в запросе содержится команда к боту
# decorator for simple command handlers
def CommandHandler(command: str, only_admin: Optional[bool] = None):
    def decorator(handlerClass):
        chat = handlerClass.chat
        sig = inspect.signature(chat)
        # параметр для спаршенных аргументов
        send_arguments = len(sig.parameters.keys()) > 3

        @wraps(handlerClass.chat)
        async def filteredChat(
            self,
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
        ):
            validation_result = validate_command_msg(update, command)
            if not validation_result:
                return False

            if send_arguments:
                # если не все параметры запрошены в сигнатуре метода
                kwargs = {
                    k: v
                    for k, v in (validation_result.args or {})
                    if k in sig.parameters.keys()
                }
                return await chat(self, update, context, **kwargs)

            return await chat(self, update, context)

        handlerClass.only_for_admin = only_admin is True
        handlerClass.chat = filteredChat
        return handlerClass

    return decorator
