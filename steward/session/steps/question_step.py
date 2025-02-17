from typing import Callable

from steward.helpers.validation import Error, Validator, call_validator_callable
from steward.session.step import Step


def text_data_converter(text_filter_func):
    return lambda update: text_filter_func(update.message.text)


class QuestionStep(Step):
    def __init__(
        self,
        key: str,
        question: str | Callable[[dict], str],
        filter_answer: Validator,
        write_question: Callable[[dict], bool] = lambda c: True,
    ):
        self.key = key
        self.question = question
        self.filter_answer = filter_answer
        self.is_waiting = False
        self.write_question = write_question

    async def chat(self, context):
        if not self.is_waiting:
            if self.write_question(context.session_context):
                await context.message.reply_text(
                    self.question(context.session_context)
                    if callable(self.question)
                    else self.question
                )
            self.is_waiting = True
            return False  # to stay on this handler in session

        filter_result = call_validator_callable(
            self.filter_answer,
            context.update,
            context.session_context,
        )
        if isinstance(filter_result, Error):
            await context.message.reply_text(filter_result.message)
            return False

        self.is_waiting = False
        context.session_context[self.key] = (
            filter_result if filter_result is not None else context.update
        )
        return True

    async def callback(self, context) -> bool:
        if not self.is_waiting:
            if self.write_question(context.session_context):
                await context.callback_query.message.chat.send_message(
                    self.question(context.session_context)
                    if callable(self.question)
                    else self.question
                )
            self.is_waiting = True
        return False

    def stop(self):
        self.is_waiting = False
