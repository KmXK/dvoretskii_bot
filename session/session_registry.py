from telegram import Message

sessions = {}


def activate_session(handler, message: Message):
    print('activate session')
    sessions[message.chat_id, message.from_user.id] = handler

def try_get_session_handler(message: Message):
    if (message.chat.id, message.from_user.id) in sessions:
        return sessions[message.chat_id, message.from_user.id]

def deactivate_session(message: Message):
    print('deactivate session')
    sessions.pop((message.chat.id, message.from_user.id), None)