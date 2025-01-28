from typing import Callable

from telegram import Update

from helpers.validation import Error, Validator, call_validator_callable
from session.step import Step


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

    async def chat(self, update, session_context):
        if not self.is_waiting:
            if self.write_question(session_context):
                await update.message.reply_text(
                    self.question(session_context)
                    if callable(self.question)
                    else self.question
                )
            self.is_waiting = True
            return False  # to stay on this handler in session

        filter_result = call_validator_callable(
            self.filter_answer,
            update,
            session_context,
        )
        if isinstance(filter_result, Error):
            await update.message.reply_text(filter_result.message)
            return False

        self.is_waiting = False
        session_context[self.key] = (
            filter_result if filter_result is not None else update
        )
        return True

    async def callback(self, update: Update, session_context: dict) -> bool:
        if not self.is_waiting:
            if self.write_question(session_context):
                await update.callback_query.message.chat.send_message(
                    self.question(session_context)
                    if callable(self.question)
                    else self.question
                )
            self.is_waiting = True
        return False

    def stop(self):
        self.is_waiting = False
