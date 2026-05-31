"""REST для привязки устройств (Galaxy Watch и т.п.) к аккаунту.

Пэйринг по коду из вебаппы → долгоживущий bearer-токен у часов. Сам счёт
часы ведут через обычные теннисные REST-ручки (см. tennis_routes), которые
после bearer-авторизации работают так же, как из браузера.
"""
from __future__ import annotations

import logging

from aiohttp import web

from steward.api.auth import require_user
from steward.api.watch_pairing import claim_code, revoke_device, start_pairing
from steward.data.repository import Repository

logger = logging.getLogger(__name__)


def _display_name(repository: Repository, user_id: int) -> str:
    user = next((u for u in repository.db.users if u.id == user_id), None)
    if user is None:
        return f"id{user_id}"
    if getattr(user, "username", None):
        return f"@{user.username}"
    return getattr(user, "first_name", None) or f"id{user_id}"


def _serialize_device(d) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
    }


async def pair_start(request: web.Request) -> web.Response:
    """POST /api/watch/pair/start — выдать одноразовый код для привязки часов."""
    user_id = require_user(request)
    code, ttl = start_pairing(user_id)
    return web.json_response({"code": code, "expires_in": ttl})


async def pair_claim(request: web.Request) -> web.Response:
    """POST /api/watch/pair/claim {code, device_name?} — обмен кода на токен.

    Публичная ручка: у часов своей сессии ещё нет. При успехе создаётся
    устройство и возвращается сырой bearer-токен (единственный раз).
    """
    repository: Repository = request.app["repository"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    code = str(body.get("code", ""))
    device_name = str(body.get("device_name", ""))
    result = claim_code(repository, code, device_name)
    if result is None:
        return web.json_response({"error": "код неверный или истёк"}, status=404)
    device, raw_token = result
    await repository.save()
    return web.json_response(
        {
            "token": raw_token,
            "user_id": device.user_id,
            "user_name": _display_name(repository, device.user_id),
            "device": _serialize_device(device),
        },
        status=201,
    )


async def list_devices(request: web.Request) -> web.Response:
    """GET /api/watch/devices — мои привязанные устройства."""
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    devices = [
        _serialize_device(d)
        for d in repository.db.paired_devices
        if d.user_id == user_id
    ]
    devices.sort(key=lambda d: d["created_at"] or "", reverse=True)
    return web.json_response({"devices": devices})


async def delete_device(request: web.Request) -> web.Response:
    """DELETE /api/watch/devices/{id} — отозвать токен устройства."""
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    try:
        device_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad id"}, status=400)
    if not revoke_device(repository, user_id, device_id):
        return web.json_response({"error": "not found"}, status=404)
    await repository.save()
    return web.json_response({"ok": True})


async def me(request: web.Request) -> web.Response:
    """GET /api/watch/me — кто я (для проверки токена часами)."""
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    return web.json_response(
        {"user_id": user_id, "user_name": _display_name(repository, user_id)}
    )


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/watch/pair/start", pair_start)
    app.router.add_post("/api/watch/pair/claim", pair_claim)
    app.router.add_get("/api/watch/devices", list_devices)
    app.router.add_delete("/api/watch/devices/{id}", delete_device)
    app.router.add_get("/api/watch/me", me)
