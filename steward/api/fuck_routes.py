"""HTTP API for managing /fuck assets.

Auth model:
- POST /api/auth/webapp     {"initData": "..."}              → set session cookie
- POST /api/auth/widget     {<login widget payload>}          → set session cookie
- GET  /api/auth/me                                           → {user_id, username, is_admin}
- POST /api/auth/logout                                       → clear cookie
- GET  /api/fuck/assets                                       → list visible to current user
- DELETE /api/fuck/assets/{id}                                → admin or owner
- PATCH  /api/fuck/assets/{id}  {"name"?: str, "scope"?: ...} → admin or owner
- GET  /api/fuck/assets/{id}/media                            → raw media bytes (for preview)
- GET  /api/fuck/assets/{id}/data                             → annotation JSON
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from pathlib import Path

from aiohttp import web

from steward.data.models.fuck_asset import FuckAsset
from steward.data.models.user import User

from steward.api.auth import (
    clear_session_cookie,
    require_admin,
    require_user,
    session_user_id,
    set_session_cookie,
    validate_login_widget,
    validate_webapp_init_data,
)
from steward.data.repository import Repository
from steward.helpers.avatars import (
    cached_avatar_path,
    save_photo_from_url,
    try_fetch_from_bot,
)

logger = logging.getLogger(__name__)

ASSETS_DIR = Path("data/fuck")
ALLOWED_SCOPES = {"global", "personal"}
ALLOWED_EXTENSIONS = {"webp", "gif", "mp4", "webm", "mov"}
MAX_FILE_BYTES = 30 * 1024 * 1024  # 30 MB


# === Helpers ===

def _serialize_asset(repository: Repository, asset, viewer_id: int) -> dict:
    owner_username = None
    for u in repository.db.users:
        if u.id == asset.owner_id:
            owner_username = u.username
            break
    return {
        "id": asset.id,
        "owner_id": asset.owner_id,
        "owner_username": owner_username,
        "name": asset.name,
        "scope": asset.scope,
        "extension": asset.extension,
        "created_at": asset.created_at,
        "can_edit": viewer_id == asset.owner_id or viewer_id in repository.db.admin_ids,
        "media_url": f"/api/fuck/assets/{asset.id}/media",
    }


def _find_asset(repository: Repository, asset_id: str):
    return next((a for a in repository.db.fuck_assets if a.id == asset_id), None)


def _assert_writable(repository: Repository, asset, user_id: int) -> None:
    if user_id == asset.owner_id:
        return
    if user_id in repository.db.admin_ids:
        return
    raise web.HTTPForbidden(reason="not owner or admin")


def _asset_dir(asset) -> Path:
    return ASSETS_DIR / str(asset.owner_id)


def _asset_paths(asset) -> tuple[Path, Path]:
    d = _asset_dir(asset)
    return d / f"{asset.id}.{asset.extension}", d / f"{asset.id}.json"


# === Auth handlers ===

async def handle_auth_config(request: web.Request):
    bot = request.app.get("bot")
    bot_username = getattr(bot, "username", None) if bot else None
    return web.json_response({"bot_username": bot_username})


async def _ingest_auth_user(
    repository: Repository,
    user_id: int,
    username: str | None,
    first_name: str | None,
) -> None:
    if not (username or first_name):
        return
    u = next((x for x in repository.db.users if x.id == user_id), None)
    changed = False
    if u is None:
        repository.db.users.append(User(user_id, username, [], first_name=first_name))
        changed = True
    else:
        if username and u.username != username:
            u.username = username
            changed = True
        if first_name and u.first_name != first_name:
            u.first_name = first_name
            changed = True
    if changed:
        await repository.save()


_AVATAR_BG_TASKS: set[asyncio.Task] = set()


def _schedule_bot_avatar_fallback(request: web.Request, user_id: int) -> None:
    from steward.helpers.avatars import has_cached_avatar
    if has_cached_avatar(user_id):
        return
    bot = request.app.get("bot")
    if bot is None:
        return

    async def _do():
        try:
            await try_fetch_from_bot(bot, user_id)
        except Exception:
            logger.exception("bot-api avatar fallback for %s failed", user_id)

    task = asyncio.create_task(_do())
    _AVATAR_BG_TASKS.add(task)
    task.add_done_callback(_AVATAR_BG_TASKS.discard)


async def _capture_avatar_on_auth(
    request: web.Request, user_id: int, photo_url: str | None
) -> None:
    if photo_url:
        try:
            path = await save_photo_from_url(user_id, photo_url)
            if path is not None:
                return
        except Exception:
            logger.exception("photo_url capture for %s failed", user_id)
    _schedule_bot_avatar_fallback(request, user_id)


async def handle_auth_webapp(request: web.Request):
    repository: Repository = request.app["repository"]
    body = await request.json()
    user = validate_webapp_init_data(str(body.get("initData", "")))
    if not user:
        logger.info("auth/webapp: invalid initData (origin=%s)", request.headers.get("Origin"))
        return web.json_response({"error": "invalid initData"}, status=403)
    uid = int(user["id"])
    try:
        await _ingest_auth_user(repository, uid, user.get("username"), user.get("first_name"))
    except Exception:
        logger.exception("auth/webapp: ingest_user failed for %s — continuing", uid)
    try:
        await _capture_avatar_on_auth(request, uid, user.get("photo_url"))
    except Exception:
        logger.exception("auth/webapp: avatar capture failed for %s — continuing", uid)
    resp = web.json_response({"user_id": uid})
    set_session_cookie(resp, uid)
    return resp


async def handle_auth_widget(request: web.Request):
    repository: Repository = request.app["repository"]
    body = await request.json()
    user = validate_login_widget(body)
    if not user:
        logger.info(
            "auth/widget: invalid signature (origin=%s, keys=%s)",
            request.headers.get("Origin"),
            sorted(body.keys()) if isinstance(body, dict) else type(body).__name__,
        )
        return web.json_response({"error": "invalid signature"}, status=403)
    uid = int(user["id"])
    try:
        await _ingest_auth_user(repository, uid, user.get("username"), user.get("first_name"))
    except Exception:
        logger.exception("auth/widget: ingest_user failed for %s — continuing", uid)
    try:
        await _capture_avatar_on_auth(request, uid, user.get("photo_url"))
    except Exception:
        logger.exception("auth/widget: avatar capture failed for %s — continuing", uid)
    resp = web.json_response({"user_id": uid})
    set_session_cookie(resp, uid)
    return resp


async def handle_auth_me(request: web.Request):
    repository: Repository = request.app["repository"]
    uid = session_user_id(request)
    if uid is None:
        return web.json_response({"authenticated": False})
    user = next((u for u in repository.db.users if u.id == uid), None)
    return web.json_response({
        "authenticated": True,
        "user_id": uid,
        "username": user.username if user else None,
        "first_name": user.first_name if user else None,
        "is_admin": uid in repository.db.admin_ids,
    })


async def handle_auth_logout(request: web.Request):
    resp = web.json_response({"ok": True})
    clear_session_cookie(resp)
    return resp


# === Asset CRUD ===

async def handle_list_assets(request: web.Request):
    repository: Repository = request.app["repository"]
    viewer = require_user(request)
    is_admin = viewer in repository.db.admin_ids
    out = []
    for asset in repository.db.fuck_assets:
        if not is_admin:
            # Non-admin sees: own assets + global assets + personal assets where they share a chat with the owner
            if asset.owner_id == viewer:
                pass
            elif asset.scope == "global":
                pass
            elif asset.scope == "personal":
                owner = next((u for u in repository.db.users if u.id == asset.owner_id), None)
                viewer_user = next((u for u in repository.db.users if u.id == viewer), None)
                if owner is None or viewer_user is None:
                    continue
                shared_chats = set(owner.chat_ids or []) & set(viewer_user.chat_ids or [])
                if not shared_chats:
                    continue
            else:
                continue
        out.append(_serialize_asset(repository, asset, viewer))
    out.sort(key=lambda a: a["created_at"], reverse=True)
    return web.json_response(out)


async def handle_create_asset(request: web.Request):
    repository: Repository = request.app["repository"]
    uid = require_user(request)

    file_bytes: bytes | None = None
    file_ext: str | None = None
    annotation: dict | None = None
    name: str = ""
    scope: str = "global"

    reader = await request.multipart()
    async for field in reader:
        if field.name == "file":
            filename = field.filename or ""
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in ALLOWED_EXTENSIONS:
                return web.json_response({"error": f"unsupported extension: {ext or '?'}"}, status=400)
            file_ext = ext
            buf = bytearray()
            while True:
                chunk = await field.read_chunk(64 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > MAX_FILE_BYTES:
                    return web.json_response({"error": "file too large"}, status=413)
            file_bytes = bytes(buf)
        elif field.name == "annotations":
            try:
                annotation = json.loads((await field.read()).decode("utf-8"))
            except Exception:
                return web.json_response({"error": "annotations is not valid JSON"}, status=400)
        elif field.name == "name":
            name = (await field.read()).decode("utf-8").strip()
        elif field.name == "scope":
            scope = (await field.read()).decode("utf-8").strip()

    if not file_bytes or not file_ext:
        return web.json_response({"error": "missing file"}, status=400)
    if not annotation:
        return web.json_response({"error": "missing annotations"}, status=400)
    if not name:
        return web.json_response({"error": "missing name"}, status=400)
    if scope not in ALLOWED_SCOPES:
        return web.json_response({"error": "invalid scope"}, status=400)

    asset_id = uuid.uuid4().hex
    owner_dir = ASSETS_DIR / str(uid)
    owner_dir.mkdir(parents=True, exist_ok=True)

    media_path = owner_dir / f"{asset_id}.{file_ext}"
    ann_path = owner_dir / f"{asset_id}.json"
    media_path.write_bytes(file_bytes)
    ann_path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")

    asset = FuckAsset(
        id=asset_id,
        owner_id=uid,
        name=name[:100],
        scope=scope,
        extension=file_ext,
        created_at=int(time.time()),
    )
    repository.db.fuck_assets.append(asset)
    await repository.save()
    logger.info("/fuck create: %s by user %s (scope=%s, ext=%s)", asset_id, uid, scope, file_ext)
    return web.json_response(_serialize_asset(repository, asset, uid))


async def handle_delete_asset(request: web.Request):
    repository: Repository = request.app["repository"]
    uid = require_user(request)
    asset_id = request.match_info["id"]
    asset = _find_asset(repository, asset_id)
    if asset is None:
        return web.json_response({"error": "not found"}, status=404)
    _assert_writable(repository, asset, uid)

    media, ann = _asset_paths(asset)
    for p in (media, ann):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            logger.warning("failed to delete %s", p, exc_info=True)
    repository.db.fuck_assets[:] = [a for a in repository.db.fuck_assets if a.id != asset_id]
    await repository.save()
    return web.json_response({"ok": True})


async def handle_patch_asset(request: web.Request):
    repository: Repository = request.app["repository"]
    uid = require_user(request)
    asset_id = request.match_info["id"]
    asset = _find_asset(repository, asset_id)
    if asset is None:
        return web.json_response({"error": "not found"}, status=404)
    _assert_writable(repository, asset, uid)

    body = await request.json()
    if "name" in body:
        name = str(body["name"]).strip()
        if name:
            asset.name = name[:100]
    if "scope" in body:
        scope = str(body["scope"])
        if scope in ALLOWED_SCOPES:
            asset.scope = scope
    if "annotations" in body:
        annotations = body["annotations"]
        if not isinstance(annotations, dict):
            return web.json_response({"error": "annotations must be an object"}, status=400)
        kfs = annotations.get("keyframes") or {}
        ka = kfs.get("a") if isinstance(kfs, dict) else None
        kb = kfs.get("b") if isinstance(kfs, dict) else None
        _, ann_path = _asset_paths(asset)
        ann_path.parent.mkdir(parents=True, exist_ok=True)
        ann_path.write_text(json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "/fuck patch: %s by user %s keyframes A=%d B=%d -> %s (%d bytes)",
            asset_id, uid,
            len(ka) if isinstance(ka, list) else -1,
            len(kb) if isinstance(kb, list) else -1,
            ann_path, ann_path.stat().st_size,
        )
    await repository.save()
    return web.json_response(_serialize_asset(repository, asset, uid))


_EXT_CONTENT_TYPE = {
    "gif": "image/gif",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
}


async def handle_get_asset_media(request: web.Request):
    repository: Repository = request.app["repository"]
    require_user(request)
    asset = _find_asset(repository, request.match_info["id"])
    if asset is None:
        raise web.HTTPNotFound()
    media, _ = _asset_paths(asset)
    if not media.exists():
        raise web.HTTPNotFound()
    headers = {"Cache-Control": "private, max-age=300"}
    ct = _EXT_CONTENT_TYPE.get(asset.extension)
    if ct:
        headers["Content-Type"] = ct
    return web.FileResponse(media, headers=headers)


async def handle_get_asset_data(request: web.Request):
    repository: Repository = request.app["repository"]
    require_user(request)
    asset = _find_asset(repository, request.match_info["id"])
    if asset is None:
        raise web.HTTPNotFound()
    _, ann = _asset_paths(asset)
    if not ann.exists():
        raise web.HTTPNotFound()
    return web.Response(
        body=ann.read_bytes(),
        headers={"Cache-Control": "no-cache"},
        content_type="application/json",
    )


_AVATAR_CONTENT_TYPE = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


async def handle_get_avatar(request: web.Request):
    require_user(request)
    try:
        target_uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    path = cached_avatar_path(target_uid)
    if path is None:
        raise web.HTTPNotFound()
    ct = _AVATAR_CONTENT_TYPE.get(path.suffix.lstrip(".").lower(), "application/octet-stream")
    return web.FileResponse(
        path,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Type": ct,
        },
    )


# === Route registration ===

def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/auth/config", handle_auth_config)
    app.router.add_post("/api/auth/webapp", handle_auth_webapp)
    app.router.add_post("/api/auth/widget", handle_auth_widget)
    app.router.add_get("/api/auth/me", handle_auth_me)
    app.router.add_post("/api/auth/logout", handle_auth_logout)
    app.router.add_get("/api/avatars/{user_id}", handle_get_avatar)
    app.router.add_get("/api/fuck/assets", handle_list_assets)
    app.router.add_post("/api/fuck/assets", handle_create_asset)
    app.router.add_delete("/api/fuck/assets/{id}", handle_delete_asset)
    app.router.add_patch("/api/fuck/assets/{id}", handle_patch_asset)
    app.router.add_get("/api/fuck/assets/{id}/media", handle_get_asset_media)
    app.router.add_get("/api/fuck/assets/{id}/data", handle_get_asset_data)
