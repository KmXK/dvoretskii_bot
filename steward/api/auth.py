"""Auth helpers for the web API.

Two paths to log a user in:

- Inside Telegram Mini App: client sends `Telegram.WebApp.initData` (URL-encoded
  key-value pairs signed with HMAC-SHA256, secret = HMAC(b"WebAppData", bot_token)).
- In a regular browser: Telegram Login Widget POSTs the user object (id, first_name,
  username, photo_url, auth_date, hash) signed with HMAC-SHA256, secret = SHA256(bot_token).

After successful validation we set an HttpOnly cookie with a signed session token
(`user_id:issued_at:hmac`). Subsequent API calls read the cookie via `session_user_id()`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from os import environ
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web

logger = logging.getLogger(__name__)

SESSION_COOKIE = "dvoretskii_sid"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
LOGIN_WIDGET_MAX_AGE = 60 * 60       # 1 hour: don't accept stale widget payloads


def _bot_token() -> str:
    return environ.get("TELEGRAM_BOT_TOKEN", "")


def _is_secure_env() -> bool:
    return bool(environ.get("DOMAIN")) and environ.get("DOMAIN", "").strip() != "localhost"


# === Telegram payload validation ===

def validate_webapp_init_data(init_data_raw: str) -> dict[str, Any] | None:
    """Validate Telegram WebApp initData and return the user dict, or None."""
    token = _bot_token()
    if not init_data_raw or not token:
        return None
    try:
        params = dict(parse_qsl(init_data_raw, keep_blank_values=True))
        received_hash = params.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            return None
        user_str = params.get("user")
        if not user_str:
            return None
        return json.loads(user_str)
    except Exception:
        logger.exception("validate_webapp_init_data failed")
        return None


def validate_login_widget(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Validate Telegram Login Widget payload and return the user dict, or None."""
    token = _bot_token()
    if not token or not isinstance(payload, dict):
        return None
    try:
        data = {k: v for k, v in payload.items() if k != "hash"}
        received_hash = payload.get("hash")
        if not received_hash:
            return None
        auth_date = int(data.get("auth_date", 0))
        if auth_date and time.time() - auth_date > LOGIN_WIDGET_MAX_AGE:
            return None
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(data.items())
        )
        secret = hashlib.sha256(token.encode()).digest()
        computed = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            return None
        return data
    except Exception:
        logger.exception("validate_login_widget failed")
        return None


# === Session token (HMAC-signed cookie) ===

def _session_secret() -> bytes:
    return _bot_token().encode()


def make_session_token(user_id: int) -> str:
    payload = f"{user_id}:{int(time.time())}"
    sig = hmac.new(_session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def parse_session_token(token: str) -> int | None:
    if not token:
        return None
    try:
        uid_s, ts_s, sig = token.split(":")
    except ValueError:
        return None
    payload = f"{uid_s}:{ts_s}"
    expected = hmac.new(_session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        if time.time() - int(ts_s) > SESSION_MAX_AGE:
            return None
        return int(uid_s)
    except ValueError:
        return None


def set_session_cookie(response: web.StreamResponse, user_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_is_secure_env(),
        samesite="Lax",
    )


def clear_session_cookie(response: web.StreamResponse) -> None:
    response.del_cookie(SESSION_COOKIE)


def session_user_id(request: web.Request) -> int | None:
    return parse_session_token(request.cookies.get(SESSION_COOKIE, ""))


def require_user(request: web.Request) -> int:
    uid = session_user_id(request)
    if uid is None:
        raise web.HTTPUnauthorized(reason="auth required")
    return uid


def require_admin(request: web.Request) -> int:
    uid = require_user(request)
    repository = request.app["repository"]
    if uid not in getattr(repository.db, "admin_ids", set()):
        raise web.HTTPForbidden(reason="admin only")
    return uid
