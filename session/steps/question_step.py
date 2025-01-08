from typing import Any, Callable

from telegram import Update

from session.step import Step


def text_data_converter(text_filter_func):
    return lambda update: text_filter_func(update.message.text)


class QuestionStep(Step):
    def __init__(
        self,
        key: str,
        question: str | Callable[[dict], str],
        filter_answer: Callable[[Update], str | None],
        data_converter: Callable[[Update], Any] = lambda u: u,
        write_question: Callable[[dict], bool] = lambda c: True,
    ):
        self.key = key
        self.question = question
        self.filter_answer = filter_answer
        self.is_waiting = False
        self.data_converter = data_converter
        self.write_question = write_question

    async def chat(self, update, session_context):
        if not self.is_waiting:
            if self.write_question(session_context):
                await update.message.reply_text(self.question(session_context) if callable(self.question) else self.question)
            self.is_waiting = True
            return False  # to stay on this handler in session

        error = self.filter_answer(self.data_converter(update))
        if error is not None:
            await update.message.reply_text(error)
            return False

        self.is_waiting = False
        session_context[self.key] = self.data_converter(update)
        return True

    def stop(self):
        self.is_waiting = False
