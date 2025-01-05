from telegram import Update
from telegram.ext import ContextTypes

from handlers.handler import Handler, validate_command_msg
from models.session import Session
from models.session_state import SessionState
from repository import Repository


class SessionCreationHandler(Handler):
    only_for_admin = True
    sessions = []

    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if validate_command_msg(update, 'add_rule_test'):
            session = Session(update.message.chat_id)  # TODO: add key for user_id too
            self.sessions.append(session)
            await session.next_message(update, context)
            return
        
        # TODO: /stop

        for session in self._sessionsWithChatId(update.message.chat_id):
            if await session.write_result(update, context):
                await session.next_message(update, context)
        self._clear_sessions()

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        for session in self._sessionsWithChatId(update.callback_query.message.chat.id):
            await session.process_callback(update, context)
        self._clear_sessions()

    def help(self):
        return '/add_rule_test - Добавить новое правило'

    def _clear_sessions(self):
        finish_sessions = [session for session in self.sessions if session.state == SessionState.finish]
        if len(finish_sessions) > 0:
            for session in finish_sessions:
                self.repository.add_rule(session.rule)
            self.sessions = [session for session in self.sessions if session.state != SessionState.finish]
        print(self.repository.rules)

    def _sessionsWithChatId(self, chat_id):
        return filter(lambda session: session.chat_id == chat_id, self.sessions)
