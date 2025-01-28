import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("keyboard")


@dataclass
class KeyboardParseResult:
    unique_keyboard_name: str
    metadata: str


class KeyboardParseException(Exception):
    def __init__(self, msg):
        super().__init__(msg)


def parse_keyboard(
    callback_data: str,
    delimiter: str = "|",
) -> KeyboardParseResult:
    parts = callback_data.split(delimiter)

    if len(parts) < 1:
        raise KeyboardParseException("Invalid parts count")

    return KeyboardParseResult(
        unique_keyboard_name=parts[0],
        metadata=parts[1] if len(parts) > 1 else "",
    )


def parse_and_validate_keyboard[T: KeyboardParseResult](
    unique_keyboard_name: str,
    callback_data: str,
    parse_func: Callable[[str], T] = parse_keyboard,
    **kwargs,
) -> T | None:
    try:
        result = parse_func(callback_data, **kwargs)
        if result.unique_keyboard_name == unique_keyboard_name:
            return result
        return None
    except KeyboardParseException as e:
        logger.exception(e)
        return None
