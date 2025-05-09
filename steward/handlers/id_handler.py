from telegram import MessageOriginUser, User

from steward.helpers.command_validation import validate_command_msg
from steward.helpers.validation import check, try_get, validate_update
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.steps.echo_step import AnswerStep
from steward.session.steps.jump_step import JumpStep
from steward.session.steps.question_step import QuestionStep


def write_result(user: User):
    return f"Id пользователя {user.name} = {user.id}"


# TODO: add commandHandler to SessionHandlerBase
class IdHandler(SessionHandlerBase):
    def __init__(self):
        self.only_for_admin = True
        super().__init__([
            QuestionStep(
                "name",
                "Пришли мне сообщение, чтобы узнать айди автора",
                filter_answer=validate_update([
                    check(
                        lambda update: update.message is not None
                        and isinstance(
                            update.message.forward_origin,
                            MessageOriginUser,
                        ),
                        "Некорректное сообщение, попробуй другое",
                    ),
                    try_get(lambda u: u.message.forward_origin.sender_user),
                ]),
            ),
            AnswerStep(lambda context: write_result(context["name"])),
            JumpStep(
                "loop",
                -2,
                lambda c: c["repeat_count"] > c["loop"] or c["repeat_count"] == -1,
            ),
        ])

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "id"):
            return False

        data = update.message.text.split(" ")

        if len(data) < 2:
            stop_iteration_number = -1
        elif data[1].isdigit() and int(data[1]) > 0:
            stop_iteration_number = int(data[1]) - 1
        else:
            return False

        session_context["repeat_count"] = stop_iteration_number
        return True

    def help(self):
        return "/id <количество повторений> - получить айди пользователя"
