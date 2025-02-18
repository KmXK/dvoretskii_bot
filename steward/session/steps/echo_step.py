from typing import Callable

from steward.session.step import Step


class AnswerStep(Step):
    def __init__(self, func: Callable[[dict], str], **kwargs):
        self.func = func
        self.kwargs = kwargs

    async def chat(self, context):
        await context.message.chat.send_message(
            self.func(context.session_context),
            **self.kwargs,
        )
        return True
