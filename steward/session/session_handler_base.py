from abc import abstractmethod
from typing import TypeVar

from telegram import Update

from steward.handlers.handler import Handler, validate_command_msg
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


StepType = TypeVar("StepType", bound="Step")


class SessionHandlerBase(Handler):
    def __init__(self, steps: list[StepType]):
        self.steps = steps
        self.sessions: dict[(int, int), SessionData] = {}  # type: ignore
        self.current_handler_index = 0

    @abstractmethod
    def try_activate_session(self, update: Update, session_context) -> bool:
        pass

    @abstractmethod
    async def on_session_finished(self, update: Update, session_context: dict):
        pass

    async def chat(self, update, context):
        return await self._action(
            update,
            context,
            lambda x: x._session_chat,
        )

    async def callback(self, update, context):
        return await self._action(
            update,
            context,
            lambda x: x._session_callback,
        )

    async def _action(self, update, context, func):
        if get_session_key(update) not in self.sessions:
            session = SessionData()
            if self.try_activate_session(update, session.context):
                activate_session(self, update)
                self.sessions[get_session_key(update)] = session
            else:
                return False
        elif validate_command_msg(update, "stop"):
            await self._stop_session(update, self.sessions[get_session_key(update)])
            return False

        return await func(self)(update, context)

    async def _session_chat(self, update, context):
        return await self._session_action(
            update,
            context,
            lambda h: h.chat,
        )

    async def _session_callback(self, update, context):
        return await self._session_action(
            update,
            context,
            lambda h: h.callback,
        )

    async def _session_action(self, update, context, func):
        session = self.sessions[get_session_key(update)]

        step = self.steps[session.current_handler_index]
        if await func(step)(update, session.context):
            session.current_handler_index += 1

            while session.current_handler_index < len(self.steps) and await func(
                self.steps[session.current_handler_index]
            )(
                update,
                session.context,
            ):
                session.current_handler_index += 1

            if session.current_handler_index >= len(self.steps):
                await self._stop_session(update, session)

        return True

    async def _stop_session(self, update: Update, session):
        deactivate_session(update)
        self.sessions.pop(get_session_key(update))
        await self.on_session_finished(update, session.context)

        for step in self.steps:
            step.stop()
