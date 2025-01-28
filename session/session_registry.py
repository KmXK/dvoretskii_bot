import logging

from telegram import Update

from session.session_handler_base import SessionHandlerBase
from tg_update_helpers import get_from_user, get_message

logger = logging.getLogger(__name__)

type SessionKey = tuple[int, int]

sessions: dict[SessionKey, SessionHandlerBase] = {}


def get_session_key(update: Update):
    return get_message(update).chat.id, get_from_user(update).id


def activate_session(handler: SessionHandlerBase, update: Update):
    logger.info("activate session")
    sessions[get_session_key(update)] = handler


def try_get_session_handler(update: Update):
    key = get_session_key(update)
    if key in sessions:
        return sessions[key]
    return None


def deactivate_session(update: Update):
    logger.info("deactivate session")
    sessions.pop(get_session_key(update), None)
