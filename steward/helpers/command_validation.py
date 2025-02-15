import logging
import re

from telegram import MessageEntity, Update

from steward.data.repository import Repository
from steward.helpers.tg_update_helpers import get_from_user

logger = logging.getLogger(__name__)


def validate_arguments(
    argument_string: str,
    argument_regex: str | re.Pattern,
) -> dict[str, str] | None:
    if isinstance(argument_regex, str):
        argument_regex = re.compile(argument_regex)
    match = argument_regex.fullmatch(argument_string.strip())

    logger.debug(
        "validate_arguments result (%s on template %s): %s",
        match,
        argument_string,
        argument_regex,
    )

    if match is None:
        return None

    return match.groupdict()


class ValidationResult:
    def __init__(self, is_valid: bool, args: dict[str, str] | None = None) -> None:
        self.is_valid = is_valid
        self.args = args

    def __bool__(self):
        return self.is_valid


class ValidationArgumentsError(BaseException):
    pass


def validate_command_msg(
    update: Update,
    command: str | list[str],
    argument_regex: re.Pattern | str | None = None,
) -> ValidationResult:
    if isinstance(command, list):
        for c in command:
            result = validate_command_msg(update, c, argument_regex)
            if result is not None:
                return result
        return ValidationResult(False)

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
                # команда не подходит для данного хэндлера
                return ValidationResult(False)

            if argument_regex is not None:
                args = validate_arguments(
                    message.text[message.entities[0].length :],
                    argument_regex,
                )
                if args is None:
                    raise ValidationArgumentsError()
                return ValidationResult(True, args)

            return ValidationResult(True)
    return ValidationResult(False)  # не команда


def validate_admin(update: Update, repository: Repository):
    from_user = get_from_user(update)
    return from_user and repository.is_admin(from_user.id)
