import inspect
import logging
from typing import Any, Callable

logger = logging.getLogger("validation")


class Error:
    def __init__(self, message: str):
        self.message = message


type ValidatorCallable[TReturn] = (
    Callable[[Any], TReturn] | Callable[[Any, dict], TReturn]
)

type Validator = ValidatorCallable[Error | Any]


def parameters_count(callable: Callable) -> int:
    sig = inspect.signature(callable)
    return len(sig.parameters.keys())


def call_validator_callable[TReturn](
    callable: ValidatorCallable[TReturn],
    value: Any,
    session_context: dict,
) -> TReturn:
    if parameters_count(callable) == 1:
        return callable(value)  # type: ignore
    else:
        return callable(value, session_context)  # type: ignore


def validate(
    value: Any,
    session_context: dict,
    validators: list[Validator],
    return_last_value: bool = True,
) -> Error | Any:
    for validator in validators:
        value = call_validator_callable(validator, value, session_context)
        logger.debug(f"Calling validation. Result: {value}")
        if isinstance(value, Error):
            return value
    return value if return_last_value else None


def validate_update(
    validators: list[Validator], *args, **kwargs
) -> ValidatorCallable[Any]:
    return lambda update, session_context: validate(
        update,
        session_context,
        validators,
        *args,
        **kwargs,
    )


def check(
    condition: ValidatorCallable[bool],
    message: str,
    value_func: ValidatorCallable[Any] = lambda v: v,
) -> Validator:
    def wrapper(value: Any, session_context: dict) -> Error | Any:
        try:
            if not call_validator_callable(condition, value, session_context):
                return Error(message)
            return call_validator_callable(value_func, value, session_context)
        except Exception:
            return Error(message)

    return wrapper


def try_get(
    converter: ValidatorCallable[Any],
    message: str = "Ошибка! Попробуйте ещё раз",
) -> Validator:
    def wrapper(value: Any, session_context: dict) -> Error | Any:
        try:
            value = call_validator_callable(converter, value, session_context)
            return value
        except Exception:
            return Error(message)

    return wrapper


def validate_message_text(validators: list[Validator], *args, **kwargs) -> Validator:
    return validate_update(
        [
            try_get(lambda u: u.message.text),
            check(
                lambda text: text is not None and len(text) > 0,
                "Сообщение не может быть пустым",
            ),
            *validators,
        ],
        *args,
        **kwargs,
    )
