from abc import abstractmethod

from telegram import Update

from handlers.handler import Handler, validate_command_msg
from session import session_registry
from session.step import Step
from tg_update_helpers import get_from_user, get_message


class SessionData:
    def __init__(self):
        self.current_handler_index = 0
        self.context = {"__internal_session_data__": self}


def get_session_key(update: Update):
    return get_message(update).chat_id, get_from_user(update).id


class SessionHandlerBase(Handler):
    def __init__(self, steps: list[Step]):
        self.steps = steps
        self.sessions: dict[(int, int), SessionData] = {}
        self.current_handler_index = 0

    @abstractmethod
    def try_activate_session(self, update: Update, session_context) -> bool:
        pass

    @abstractmethod
    def on_session_finished(self, update: Update, session_context: dict):
        pass

    async def chat(self, update, context):
        return await self._action(update, context, lambda x: x._session_chat)

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
                session_registry.activate_session(self, get_message(update))
                self.sessions[get_session_key(update)] = session
            else:
                return False
        elif validate_command_msg(update, "stop"):
            self._stop_session(update, self.sessions[get_session_key(update)])
            return False

        return await func(self)(update, context)

    async def _session_chat(self, update, context):
        return await self._session_action(update, context, lambda h: h.chat)

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
                self._stop_session(update, session)

        return True

    def _stop_session(self, update, session):
        session_registry.deactivate_session(get_message(update))
        self.sessions.pop(get_session_key(update))
        self.on_session_finished(update, session.context)

        for step in self.steps:
            step.stop()
