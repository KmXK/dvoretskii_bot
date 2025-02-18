from steward.helpers.command_validation import validate_command_msg
from steward.helpers.validation import check, try_get, validate_update
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.steps.echo_step import AnswerStep
from steward.session.steps.question_step import QuestionStep


class MessageInfoHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__([
            QuestionStep(
                "name",
                "Пришли мне сообщение, чтобы увидеть дебаг инфу",
                filter_answer=validate_update([
                    check(
                        lambda update: update.message is not None,
                        "Некорректное сообщение, попробуй другое",
                    ),
                    try_get(lambda u: u.message),
                ]),
            ),
            AnswerStep(
                lambda context: f"```\n{str(context['name'])}```",
                parse_mode="markdown",
            ),
        ])

    def try_activate_session(self, update, session_context):
        return validate_command_msg(update, "debug_msg")

    def help(self):
        return "/debug_msg - выводит информацию о сообщении"
