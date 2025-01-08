from typing import Callable
from session.step import Step


class JumpStep(Step):
    def __init__(
        self,
        iteration_key: str,
        relative_step_index: int,
        condition: Callable[[dict], bool] = lambda c: True,
    ):
        self.iteration_key = iteration_key
        self.relative_step_index = relative_step_index
        self.condition = condition

        self.counter = 0

    async def chat(self, update, session_context):
        return self._jump(session_context)

    async def callback(self, update, session_context):
        return self._jump(session_context)

    def _jump(self, session_context):
        if self.iteration_key not in session_context:
            session_context[self.iteration_key] = 0

        if self.condition(session_context):
            jump_count = self.relative_step_index
        else:
            jump_count = 1

        # после выполнения хендлера добавляется единица самостоятельно
        session_context["__internal_session_data__"].current_handler_index += jump_count - 1
        session_context[self.iteration_key] += 1

        return True
