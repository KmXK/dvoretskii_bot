from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from os import environ
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from aiohttp import web

logger = logging.getLogger(__name__)

SESSION_COOKIE = "dvoretskii_sid"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
LOGIN_WIDGET_MAX_AGE = 60 * 60
INIT_DATA_MAX_AGE = 60 * 60 * 24
INIT_DATA_HEADER = "X-Init-Data"


def _bot_token() -> str:
    return environ.get("TELEGRAM_BOT_TOKEN", "")


def _is_secure_env() -> bool:
    return bool(environ.get("DOMAIN")) and environ.get("DOMAIN", "").strip() != "localhost"


def _allowed_origins() -> set[str]:
    domain = environ.get("DOMAIN", "").strip()
    if not domain or domain == "localhost":
        return set()
    return {f"https://{domain}", f"http://{domain}"}


def validate_webapp_init_data(init_data_raw: str, *, enforce_freshness: bool = False) -> dict[str, Any] | None:
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
        if enforce_freshness:
            try:
                auth_date = int(params.get("auth_date", "0"))
            except ValueError:
                return None
            if auth_date and time.time() - auth_date > INIT_DATA_MAX_AGE:
                return None
        user_str = params.get("user")
        if not user_str:
            return None
        return json.loads(user_str)
    except Exception:
        logger.exception("validate_webapp_init_data failed")
        return None


def validate_login_widget(payload: dict[str, Any]) -> dict[str, Any] | None:
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
    secure = _is_secure_env()
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="Lax",
    )


def clear_session_cookie(response: web.StreamResponse) -> None:
    response.del_cookie(SESSION_COOKIE)


def _init_data_user_id(request: web.Request) -> int | None:
    init_data = request.headers.get(INIT_DATA_HEADER, "")
    if not init_data:
        return None
    user = validate_webapp_init_data(init_data, enforce_freshness=True)
    if not user:
        return None
    try:
        return int(user["id"])
    except (KeyError, ValueError, TypeError):
        return None


def session_user_id(request: web.Request) -> int | None:
    uid = parse_session_token(request.cookies.get(SESSION_COOKIE, ""))
    if uid is not None:
        return uid
    return _init_data_user_id(request)


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


PUBLIC_API_PATHS = {
    "/api/auth/config",
    "/api/auth/webapp",
    "/api/auth/widget",
    "/api/auth/me",
    "/api/auth/logout",
}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _origin_allowed(request: web.Request) -> bool:
    allowed = _allowed_origins()
    if not allowed:
        return True
    raw = request.headers.get("Origin") or request.headers.get("Referer")
    if not raw:
        return False
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return False
    origin = f"{parts.scheme}://{parts.netloc}"
    return origin in allowed


@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path
    if not path.startswith("/api/"):
        return await handler(request)
    if request.method not in SAFE_METHODS and not _origin_allowed(request):
        return web.json_response({"error": "cross-origin blocked"}, status=403)
    if path not in PUBLIC_API_PATHS and session_user_id(request) is None:
        return web.json_response({"error": "auth required"}, status=401)
    return await handler(request)


def ws_session_user(request: web.Request):
    uid = session_user_id(request)
    if uid is None:
        return None
    repository = request.app["repository"]
    user = next((u for u in repository.db.users if u.id == uid), None)
    username = (user.username if user else None) or "Player"
    return uid, username[:30]
