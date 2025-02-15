import inspect
import logging
import re
from functools import wraps
from typing import Any

from pyrate_limiter import Callable, Optional
from telegram import Update
from telegram.ext import ContextTypes

from steward.helpers.command_validation import validate_command_msg

logger = logging.getLogger(__name__)


# проверяет, что в запросе содержится команда к боту
# decorator for simple command handlers
def CommandHandler(
    command: str,
    arguments_template: Optional[str | re.Pattern] = None,
    arguments_mapping: dict[str, Callable[[str | None], Any]] = {},
    only_admin: Optional[bool] = None,
):
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
            validation_result = validate_command_msg(
                update,
                command,
                arguments_template,
            )
            if not validation_result:
                return False

            logger.debug(validation_result)

            if send_arguments:

                def get_value(name: str, value: str | None, default: str | None):
                    mapper = arguments_mapping.get(name)
                    if mapper is not None:
                        return mapper(value)
                    if value is None:
                        return default
                    return value

                # если не все параметры запрошены в сигнатуре метода
                kwargs = {
                    k: get_value(k, v, sig.parameters.get(k).default)
                    for k, v in (validation_result.args or {}).items()
                    if k in sig.parameters.keys()
                }
                return await chat(self, update, context, **kwargs)

            return await chat(self, update, context)

        handlerClass.only_for_admin = only_admin is True
        handlerClass.chat = filteredChat
        return handlerClass

    return decorator
