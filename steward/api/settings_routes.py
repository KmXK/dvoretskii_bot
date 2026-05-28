"""HTTP API for /settings — capability toggles, chat admins, roles, permissions."""

from __future__ import annotations

import logging

from aiohttp import web

from steward.api.auth import require_user, session_user_id
from steward.data.models.chat_settings import ChatSettings
from steward.data.models.role import Role, UserRole
from steward.data.repository import Repository

logger = logging.getLogger(__name__)


def _settings_for(repo: Repository, chat_id: int) -> ChatSettings:
    return repo.chat_settings_for(chat_id)


def _serialize_settings(settings: ChatSettings) -> dict:
    return {
        "chat_id": settings.chat_id,
        "enabled_capabilities": sorted(settings.enabled_capabilities),
        "disabled_features": sorted(settings.disabled_features),
        "chat_admins": sorted(settings.chat_admins),
        "onboarded": settings.onboarded,
    }


def _capabilities_meta() -> dict:
    from steward.features.registry import (
        CAPABILITIES,
        CAPABILITY_LABELS,
        feature_slug,
    )
    out: dict[str, dict] = {}
    for cap, classes in CAPABILITIES.items():
        feats = []
        for cls in sorted(classes, key=lambda c: c.__name__):
            feats.append({
                "slug": feature_slug(cls),
                "command": getattr(cls, "command", None),
                "description": getattr(cls, "description", "") or "",
                "passive": getattr(cls, "command", None) is None,
            })
        out[cap] = {
            "label": CAPABILITY_LABELS.get(cap, cap),
            "features": feats,
        }
    return out


def _can_manage_chat(repo: Repository, user_id: int, chat_id: int) -> bool:
    return repo.is_chat_admin(user_id, chat_id)


def _is_member(repo: Repository, user_id: int, chat_id: int) -> bool:
    user = next((u for u in repo.db.users if u.id == user_id), None)
    if user is None:
        return False
    return chat_id in (user.chat_ids or [])


# ── Chat settings ────────────────────────────────────────────────────────────

async def handle_user_chats_for_settings(request: web.Request):
    """List chats where caller is global-admin or chat-admin."""
    uid = require_user(request)
    repo: Repository = request.app["repository"]
    is_global = repo.is_admin(uid)
    out = []
    for chat in repo.db.chats:
        settings = _settings_for(repo, chat.id)
        if not (is_global or uid in settings.chat_admins):
            continue
        out.append({
            "id": chat.id,
            "name": chat.name,
            "is_chat_admin": uid in settings.chat_admins,
        })
    return web.json_response({"chats": out})


async def handle_chat_settings_get(request: web.Request):
    uid = require_user(request)
    repo: Repository = request.app["repository"]
    chat_id = int(request.match_info["chat_id"])
    if not (repo.is_admin(uid) or _can_manage_chat(repo, uid, chat_id) or _is_member(repo, uid, chat_id)):
        return web.json_response({"error": "forbidden"}, status=403)
    settings = _settings_for(repo, chat_id)
    return web.json_response({
        **_serialize_settings(settings),
        "capabilities": _capabilities_meta(),
        "is_chat_admin": uid in settings.chat_admins,
        "is_global_admin": repo.is_admin(uid),
    })


async def handle_chat_settings_patch(request: web.Request):
    uid = require_user(request)
    repo: Repository = request.app["repository"]
    chat_id = int(request.match_info["chat_id"])
    if not _can_manage_chat(repo, uid, chat_id):
        return web.json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    settings = _settings_for(repo, chat_id)
    from steward.features.registry import ALL_CAPABILITIES, CAPABILITIES, feature_slug

    valid_slugs: set[str] = set()
    for classes in CAPABILITIES.values():
        for cls in classes:
            valid_slugs.add(feature_slug(cls))

    if "enabled_capabilities" in body:
        caps = body["enabled_capabilities"]
        if not isinstance(caps, list):
            return web.json_response({"error": "enabled_capabilities must be list"}, status=400)
        settings.enabled_capabilities = {c for c in caps if c in ALL_CAPABILITIES}
    if "disabled_features" in body:
        feats = body["disabled_features"]
        if not isinstance(feats, list):
            return web.json_response({"error": "disabled_features must be list"}, status=400)
        settings.disabled_features = {f for f in feats if f in valid_slugs}
    await repo.save()
    return web.json_response(_serialize_settings(settings))


async def handle_chat_admin_add(request: web.Request):
    uid = require_user(request)
    repo: Repository = request.app["repository"]
    chat_id = int(request.match_info["chat_id"])
    if not _can_manage_chat(repo, uid, chat_id):
        return web.json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    target = int(body.get("user_id", 0))
    if target == 0:
        return web.json_response({"error": "user_id required"}, status=400)
    settings = _settings_for(repo, chat_id)
    settings.chat_admins.add(target)
    await repo.save()
    return web.json_response(_serialize_settings(settings))


async def handle_chat_admin_remove(request: web.Request):
    uid = require_user(request)
    repo: Repository = request.app["repository"]
    chat_id = int(request.match_info["chat_id"])
    target = int(request.match_info["user_id"])
    if not _can_manage_chat(repo, uid, chat_id):
        return web.json_response({"error": "forbidden"}, status=403)
    settings = _settings_for(repo, chat_id)
    settings.chat_admins.discard(target)
    await repo.save()
    return web.json_response(_serialize_settings(settings))


# ── Roles ───────────────────────────────────────────────────────────────────

def _serialize_role(repo: Repository, role: Role) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "permissions": sorted(role.permissions),
        "user_ids": sorted(
            ur.user_id for ur in repo.db.user_roles if ur.role_id == role.id
        ),
    }


def _require_global(request: web.Request) -> tuple[int, Repository] | web.Response:
    uid = require_user(request)
    repo: Repository = request.app["repository"]
    if not repo.is_admin(uid):
        return web.json_response({"error": "forbidden"}, status=403)
    return uid, repo


async def handle_roles_list(request: web.Request):
    result = _require_global(request)
    if isinstance(result, web.Response):
        return result
    uid, repo = result
    return web.json_response([_serialize_role(repo, r) for r in repo.db.roles])


async def handle_roles_create(request: web.Request):
    result = _require_global(request)
    if isinstance(result, web.Response):
        return result
    uid, repo = result
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    perms = body.get("permissions", []) or []
    next_id = max((r.id for r in repo.db.roles), default=0) + 1
    role = Role(id=next_id, name=name, permissions={str(p) for p in perms})
    repo.db.roles.append(role)
    await repo.save()
    return web.json_response(_serialize_role(repo, role), status=201)


async def handle_roles_patch(request: web.Request):
    result = _require_global(request)
    if isinstance(result, web.Response):
        return result
    uid, repo = result
    role_id = int(request.match_info["role_id"])
    role = next((r for r in repo.db.roles if r.id == role_id), None)
    if role is None:
        return web.json_response({"error": "not found"}, status=404)
    body = await request.json()
    if "name" in body:
        name = str(body["name"]).strip()
        if name:
            role.name = name
    if "permissions" in body:
        perms = body["permissions"] or []
        role.permissions = {str(p) for p in perms}
    await repo.save()
    return web.json_response(_serialize_role(repo, role))


async def handle_roles_delete(request: web.Request):
    result = _require_global(request)
    if isinstance(result, web.Response):
        return result
    uid, repo = result
    role_id = int(request.match_info["role_id"])
    repo.db.roles = [r for r in repo.db.roles if r.id != role_id]
    repo.db.user_roles = [ur for ur in repo.db.user_roles if ur.role_id != role_id]
    await repo.save()
    return web.json_response({"ok": True})


async def handle_role_user_add(request: web.Request):
    result = _require_global(request)
    if isinstance(result, web.Response):
        return result
    uid, repo = result
    role_id = int(request.match_info["role_id"])
    body = await request.json()
    target = int(body.get("user_id", 0))
    if target == 0:
        return web.json_response({"error": "user_id required"}, status=400)
    role = next((r for r in repo.db.roles if r.id == role_id), None)
    if role is None:
        return web.json_response({"error": "not found"}, status=404)
    if not any(ur.user_id == target and ur.role_id == role_id for ur in repo.db.user_roles):
        repo.db.user_roles.append(UserRole(user_id=target, role_id=role_id))
        await repo.save()
    return web.json_response(_serialize_role(repo, role))


async def handle_role_user_remove(request: web.Request):
    result = _require_global(request)
    if isinstance(result, web.Response):
        return result
    uid, repo = result
    role_id = int(request.match_info["role_id"])
    target = int(request.match_info["user_id"])
    repo.db.user_roles = [
        ur for ur in repo.db.user_roles
        if not (ur.role_id == role_id and ur.user_id == target)
    ]
    await repo.save()
    role = next((r for r in repo.db.roles if r.id == role_id), None)
    if role is None:
        return web.json_response({"ok": True})
    return web.json_response(_serialize_role(repo, role))


# ── Permissions catalogue ───────────────────────────────────────────────────

async def handle_permissions(request: web.Request):
    """List all permissions known to the bot (subcommand-attached + currently
    assigned to roles). Global-admin only."""
    result = _require_global(request)
    if isinstance(result, web.Response):
        return result
    uid, repo = result
    handlers = request.app.get("handlers") or []
    seen: dict[str, list[dict]] = {}
    for h in handlers:
        feature_name = h.__class__.__name__
        cmd = getattr(h, "command", None)
        for sub in getattr(h, "_subcommands", []) or []:
            if not sub.permission:
                continue
            usage = sub.raw or ""
            seen.setdefault(sub.permission, []).append({
                "feature": feature_name,
                "command": cmd,
                "subcommand": usage,
                "description": sub.description,
            })
    # include perms attached to roles but unknown
    for r in repo.db.roles:
        for p in r.permissions:
            seen.setdefault(p, [])
    out = [
        {"slug": slug, "used_by": used_by}
        for slug, used_by in sorted(seen.items())
    ]
    return web.json_response(out)


# ── Registration ────────────────────────────────────────────────────────────

def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/settings/chats", handle_user_chats_for_settings)
    app.router.add_get("/api/chats/{chat_id}/settings", handle_chat_settings_get)
    app.router.add_patch("/api/chats/{chat_id}/settings", handle_chat_settings_patch)
    app.router.add_post("/api/chats/{chat_id}/admins", handle_chat_admin_add)
    app.router.add_delete("/api/chats/{chat_id}/admins/{user_id}", handle_chat_admin_remove)
    app.router.add_get("/api/roles", handle_roles_list)
    app.router.add_post("/api/roles", handle_roles_create)
    app.router.add_patch("/api/roles/{role_id}", handle_roles_patch)
    app.router.add_delete("/api/roles/{role_id}", handle_roles_delete)
    app.router.add_post("/api/roles/{role_id}/users", handle_role_user_add)
    app.router.add_delete("/api/roles/{role_id}/users/{user_id}", handle_role_user_remove)
    app.router.add_get("/api/permissions", handle_permissions)
