from abc import abstractmethod
from typing import Awaitable

from pyrate_limiter import Callable
from telegram import Update

from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.session.context import (
    CallbackStepContext,
    ChatStepContext,
    SessionContext,
    StepContext,
)
from steward.session.session_registry import (
    activate_session,
    deactivate_session,
    get_session_key,
)
from steward.session.step import Step


class SessionData:
    def __init__(self):
        self.current_handler_index = 0
        self.context = {"__internal_session_data__": self}


class SessionHandlerBase(Handler):
    def __init__(self, steps: list[Step]):
        self.steps = steps
        self.sessions: dict[(int, int), SessionData] = {}  # type: ignore
        self.current_handler_index = 0

    @abstractmethod
    def try_activate_session(
        self,
        update: Update,
        session_context: SessionContext,
    ) -> bool:
        pass

    @abstractmethod
    async def on_session_finished(
        self,
        update: Update,
        session_context: SessionContext,
    ):
        pass

    async def chat(self, context):
        return await self._action(
            ChatStepContext(**context.__dict__, session_context={}),
            lambda step, context: step.chat(context),
        )

    async def callback(self, context):
        return await self._action(
            CallbackStepContext(**context.__dict__, session_context={}),
            lambda step, context: step.callback(context),
        )

    async def _action[TContext: StepContext](
        self,
        context: TContext,
        func: Callable[[Step, TContext], Awaitable[bool]],
    ):
        if get_session_key(context.update) not in self.sessions:
            session = SessionData()
            if self.try_activate_session(context.update, session.context):
                activate_session(self, context.update)
                self.sessions[get_session_key(context.update)] = session
            else:
                return False
        elif validate_command_msg(context.update, "stop"):
            await self._stop_session(
                context.update,
                self.sessions[get_session_key(context.update)],
            )
            return False
        else:
            session = self.sessions[get_session_key(context.update)]

        context.session_context = session.context

        step = self.steps[session.current_handler_index]
        if await func(step, context):
            session.current_handler_index += 1

            while session.current_handler_index < len(self.steps) and (
                await func(self.steps[session.current_handler_index], context)
            ):
                session.current_handler_index += 1

            if session.current_handler_index >= len(self.steps):
                await self._stop_session(context.update, session)

        return True

    async def _stop_session(self, update: Update, session: SessionData):
        deactivate_session(update)
        self.sessions.pop(get_session_key(update))
        await self.on_session_finished(update, session.context)

        for step in self.steps:
            step.stop()
