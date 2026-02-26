import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from telegram import Update

from steward.helpers.tg_update_helpers import get_from_user, get_message

logger = logging.getLogger(__name__)

type SessionKey = tuple[int, int]

# TODO: Make a class not static
sessions: dict[SessionKey, Any] = {}
session_last_activity: dict[SessionKey, datetime] = {}


def get_session_key(update: Update):
    return get_message(update).chat.id, get_from_user(update).id


def _touch_session_key(key: SessionKey):
    session_last_activity[key] = datetime.now(timezone.utc)


def touch_session(update: Update):
    _touch_session_key(get_session_key(update))


def activate_session(handler: Any, update: Update):
    logger.info("activate session")
    key = get_session_key(update)
    sessions[key] = handler
    _touch_session_key(key)


def try_get_session_handler(update: Update):
    key = get_session_key(update)
    if key in sessions:
        _touch_session_key(key)
        return sessions[key]
    return None


def deactivate_session(update: Update):
    logger.info("deactivate session")
    deactivate_session_by_key(get_session_key(update))


def deactivate_session_by_key(key: SessionKey):
    sessions.pop(key, None)
    session_last_activity.pop(key, None)


def cleanup_stale_sessions(ttl_seconds: int) -> int:
    if ttl_seconds <= 0:
        return 0

    threshold = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
    stale_keys = [k for k, ts in session_last_activity.items() if ts < threshold]
    if not stale_keys:
        return 0

    for key in stale_keys:
        handler = sessions.get(key)
        if handler is not None and hasattr(handler, "expire_session_by_key"):
            try:
                handler.expire_session_by_key(key)
            except Exception:
                logger.exception("Failed to expire stale session: %s", key)
        deactivate_session_by_key(key)
    return len(stale_keys)
