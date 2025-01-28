from typing import Callable

from steward.session.step import Step


class AnswerStep(Step):
    def __init__(self, func: Callable[[dict], str]):
        self.func = func

    async def chat(self, update, session_context):
        await update.message.chat.send_message(self.func(session_context))
        return True
