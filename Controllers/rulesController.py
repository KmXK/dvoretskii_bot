from telegram import Update
from telegram.ext import ContextTypes

from Models.session import Session
from Models.session_state import SessionState
from repository import Repository


class RulesController(object):
    sessions = []
    
    def __init__(self, repository: Repository):
        self.repository = repository

    async def open_add_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat_id
        session = Session(chat_id)
        self.sessions.append(session)
        await session.next_message(update, context)
        
    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat_id
        for session in self.sessions:
            if session.chat_id == chat_id:
                if await session.write_result(update, context):
                    await session.next_message(update, context)
        self.clear_sessions()

    async def process_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.callback_query.message.chat_id
        for session in self.sessions:
            if session.chat_id == chat_id:
                await session.process_callback(update, context)
        self.clear_sessions()
        
    def clear_sessions(self):
        finish_sessions = [session for session in self.sessions if session.state == SessionState.finish]
        if (len(finish_sessions)):
            for session in finish_sessions:
                self.repository.add_rule(session.rule)
            self.sessions = [session for session in self.sessions if session not in finish_sessions]
        print(self.repository.rules)
