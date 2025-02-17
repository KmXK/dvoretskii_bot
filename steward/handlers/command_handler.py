import inspect
import logging
import re
from functools import wraps
from typing import Any

from pyrate_limiter import Callable, Optional

from steward.bot.context import ChatBotContext
from steward.helpers.command_validation import (
    ValidationArgumentsError,
    validate_command_msg,
)

logger = logging.getLogger(__name__)


type Mapping[T] = Callable[[str | None], T]


# костыль для типизации обязательных параметров, чтобы не всплывал None
# может быть стоит как-то по-другому это обыграть, не хочу много лишнего кода, а так лишь одна функция (# TODO)
def required[T](func: Callable[[str], T]) -> Mapping[T]:
    def wrapper(value: str | None):
        assert value
        return func(value)

    return wrapper


# проверяет, что в запросе содержится команда к боту
# decorator for simple command handlers
def CommandHandler(
    command: str,
    arguments_template: Optional[str | re.Pattern] = None,
    arguments_mapping: dict[str, Mapping[Any]] = {},  # TODO: better typing?
    only_admin: Optional[bool] = None,
):
    def decorator(handlerClass):
        chat = handlerClass.chat
        sig = inspect.signature(chat)
        # параметр для спаршенных аргументов
        send_arguments = len(sig.parameters.keys()) > 2

        @wraps(handlerClass.chat)
        async def filteredChat(self, context: ChatBotContext):
            validation_result = validate_command_msg(
                context.update,
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
                try:
                    kwargs = {
                        k: get_value(k, v, sig.parameters.get(k).default)
                        for k, v in (validation_result.args or {}).items()
                        if k in sig.parameters.keys()
                    }
                except BaseException as e:
                    logger.exception(e)
                    # TODO: move get_value to command_validation
                    raise ValidationArgumentsError()

                return await chat(self, context, **kwargs)

            return await chat(self, context)

        handlerClass.only_for_admin = only_admin is True
        handlerClass.chat = filteredChat
        return handlerClass

    return decorator
