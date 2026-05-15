"""REST endpoints для теннисной фичи — питают веб-аппу.

Авторизация — через cookie/X-Init-Data middleware (auth_middleware в server.py
блокирует анонимов на /api/*). Внутри ручек берём user_id из session_user_id.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiohttp import web

from steward.api.auth import require_user
from steward.data.models.tennis import TennisMatch, TennisSession
from steward.data.repository import Repository
from steward.tennis.engine import (
    SIDE_A,
    SIDE_B,
    aggregate_session_matches,
    player_stats,
    server_progress,
    session_wins,
)
from steward.tennis.import_parser import BulkEntry, parse_bulk_history
from steward.tennis.room_manager import _iso_utc, get_manager

logger = logging.getLogger(__name__)


# ── serialization ─────────────────────────────────────────────────────────────

def _display(repository: Repository, user_id: int) -> str:
    user = next((u for u in repository.db.users if u.id == user_id), None)
    if user is None:
        return f"id{user_id}"
    if getattr(user, "username", None):
        return f"@{user.username}"
    return getattr(user, "first_name", None) or f"id{user_id}"


def _spoken_name(repository: Repository, user_id: int, fallback: str) -> str:
    raw = _display(repository, user_id)
    if not raw or raw.startswith("id"):
        return fallback
    return raw.lstrip("@")


def _serialize_match(m: TennisMatch) -> dict:
    return {
        "started_at": _iso_utc(m.started_at),
        "ended_at": _iso_utc(m.ended_at),
        "winner": m.winner,
        "score_a": m.score_a,
        "score_b": m.score_b,
    }


def _serialize_session(
    repository: Repository,
    s: TennisSession,
    *,
    detailed: bool = False,
) -> dict:
    wins_a, wins_b = session_wins(s)
    server, srv_n, srv_total = server_progress(
        s.first_server, s.current_score_a, s.current_score_b
    )
    payload = {
        "id": s.id,
        "chat_id": s.chat_id,
        "player_a_id": s.player_a_id,
        "player_b_id": s.player_b_id,
        "player_a_name": _spoken_name(repository, s.player_a_id, "игрок А"),
        "player_b_name": _spoken_name(repository, s.player_b_id, "игрок Б"),
        "started_at": _iso_utc(s.started_at),
        "ended_at": _iso_utc(s.ended_at),
        "last_activity_at": _iso_utc(s.last_activity_at),
        "is_aggregate_only": s.is_aggregate_only,
        "closed_reason": s.closed_reason,
        "note": s.note,
        "initiator_id": s.initiator_id,
        "wins": [wins_a, wins_b],
        "matches_count": len(s.matches),
        "first_server": s.first_server,
        "server": server,
        "server_progress": [srv_n, srv_total],
        "set_size": s.set_size,
        "current_score": [s.current_score_a, s.current_score_b],
        "duration_seconds": (
            (s.ended_at - s.started_at).total_seconds() if s.ended_at else None
        ),
    }
    if detailed:
        payload["matches"] = [_serialize_match(m) for m in s.matches]
    return payload


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_user(repository: Repository, identifier: Any) -> int | None:
    """Возвращает user_id по идентификатору. Принимает int (id), str (@username|id)."""
    if isinstance(identifier, int):
        user = next((u for u in repository.db.users if u.id == identifier), None)
        return user.id if user else None
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    raw = identifier.strip().lstrip("@")
    try:
        uid = int(raw)
        user = next((u for u in repository.db.users if u.id == uid), None)
        return user.id if user else None
    except ValueError:
        pass
    target = raw.lower()
    for u in repository.db.users:
        if u.username and u.username.lower() == target:
            return u.id
    return None


def _user_can_modify(session: TennisSession, user_id: int) -> bool:
    return user_id in (session.player_a_id, session.player_b_id, session.initiator_id)


# ── endpoints ─────────────────────────────────────────────────────────────────

async def list_sessions(request: web.Request) -> web.Response:
    """GET /api/tennis/sessions — все сессии где user_id участвует, новые первыми."""
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    relevant = [
        s for s in repository.db.tennis_sessions
        if user_id in (s.player_a_id, s.player_b_id, s.initiator_id)
    ]
    relevant.sort(key=lambda s: s.started_at, reverse=True)
    limit = int(request.query.get("limit", "30"))
    return web.json_response({
        "sessions": [_serialize_session(repository, s) for s in relevant[:limit]],
    })


async def get_session(request: web.Request) -> web.Response:
    """GET /api/tennis/sessions/{id} — детали + все партии."""
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    try:
        sid = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad id"}, status=400)
    session = next((s for s in repository.db.tennis_sessions if s.id == sid), None)
    if session is None:
        return web.json_response({"error": "not found"}, status=404)
    if not _user_can_modify(session, user_id):
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response(_serialize_session(repository, session, detailed=True))


async def create_session(request: web.Request) -> web.Response:
    """POST /api/tennis/sessions
    {opponent: @username|id, first_server: 'a'|'b', set_size: int, chat_id?: int}
    """
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)

    opponent_raw = body.get("opponent")
    opponent_id = _resolve_user(repository, opponent_raw)
    if opponent_id is None:
        return web.json_response(
            {"error": f"opponent «{opponent_raw}» not found"}, status=400
        )
    if opponent_id == user_id:
        return web.json_response({"error": "self play not supported"}, status=400)

    first_server = str(body.get("first_server", "a")).lower()
    if first_server not in (SIDE_A, SIDE_B):
        first_server = SIDE_A
    set_size = max(0, int(body.get("set_size", 0) or 0))

    # Один активный сеанс на пользователя в чате
    chat_id = int(body.get("chat_id") or user_id)
    existing = next(
        (
            s for s in repository.db.tennis_sessions
            if s.ended_at is None
            and s.chat_id == chat_id
            and user_id in (s.player_a_id, s.player_b_id, s.initiator_id)
        ),
        None,
    )
    if existing is not None:
        return web.json_response(
            {
                "error": "active session exists",
                "session_id": existing.id,
            },
            status=409,
        )

    now = datetime.now()
    next_id = max((s.id for s in repository.db.tennis_sessions), default=0) + 1
    session = TennisSession(
        id=next_id,
        chat_id=chat_id,
        player_a_id=user_id,
        player_b_id=opponent_id,
        started_at=now,
        last_activity_at=now,
        initiator_id=user_id,
        first_server=first_server,
        set_size=set_size,
    )
    repository.db.tennis_sessions.append(session)
    await repository.save()
    return web.json_response(_serialize_session(repository, session, detailed=True), status=201)


async def delete_session(request: web.Request) -> web.Response:
    """DELETE /api/tennis/sessions/{id} — только initiator."""
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    try:
        sid = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad id"}, status=400)
    session = next((s for s in repository.db.tennis_sessions if s.id == sid), None)
    if session is None:
        return web.json_response({"error": "not found"}, status=404)
    if session.initiator_id != user_id:
        return web.json_response({"error": "only initiator can delete"}, status=403)

    repository.db.tennis_sessions = [
        s for s in repository.db.tennis_sessions if s.id != sid
    ]
    # Если у RoomManager есть комната с этим id — удалим
    get_manager().detach(sid)
    await repository.save()
    return web.json_response({"ok": True})


async def delete_match(request: web.Request) -> web.Response:
    """DELETE /api/tennis/sessions/{id}/matches/{idx} — удалить партию по индексу."""
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    try:
        sid = int(request.match_info["id"])
        idx = int(request.match_info["idx"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad params"}, status=400)
    session = next((s for s in repository.db.tennis_sessions if s.id == sid), None)
    if session is None:
        return web.json_response({"error": "not found"}, status=404)
    if not _user_can_modify(session, user_id):
        return web.json_response({"error": "forbidden"}, status=403)
    if idx < 0 or idx >= len(session.matches):
        return web.json_response({"error": "bad index"}, status=400)
    session.matches.pop(idx)
    # обновим sets_announced если стало меньше
    if session.set_size > 0:
        session.sets_announced = min(
            session.sets_announced,
            len(session.matches) // session.set_size,
        )
    session.last_activity_at = datetime.now()
    await repository.save()
    # Если активная live-комната — пушнём обновлённый state
    room = get_manager().get_room(sid)
    if room is not None and session.ended_at is None:
        await room.broadcast()
    return web.json_response(_serialize_session(repository, session, detailed=True))


async def get_stats(request: web.Request) -> web.Response:
    """GET /api/tennis/stats?user_id=... — статистика по игроку (по умолчанию я)."""
    me = require_user(request)
    repository: Repository = request.app["repository"]
    target_raw = request.query.get("user_id")
    if target_raw:
        try:
            target_id = int(target_raw)
        except ValueError:
            return web.json_response({"error": "bad user_id"}, status=400)
    else:
        target_id = me

    stats = player_stats(list(repository.db.tennis_sessions), target_id)
    return web.json_response({
        "user_id": stats.user_id,
        "user_name": _spoken_name(repository, target_id, f"id{target_id}"),
        "sessions": stats.sessions,
        "matches": stats.matches,
        "wins": stats.wins,
        "losses": stats.losses,
        "win_rate": stats.win_rate,
        "median_matches_per_session": stats.median_matches_per_session,
        "median_point_diff": stats.median_point_diff,
        "median_match_duration_s": stats.median_match_duration_s,
        "median_gap_s": stats.median_gap_s,
        "longest_win_streak": stats.longest_win_streak,
    })


async def list_opponents(request: web.Request) -> web.Response:
    """GET /api/tennis/opponents — кандидаты для нового матча.

    Берём пользователей из общих чатов с тобой; плюс уже-сыгравшие оппоненты.
    """
    me = require_user(request)
    repository: Repository = request.app["repository"]
    my_user = next((u for u in repository.db.users if u.id == me), None)
    my_chats = set(getattr(my_user, "chat_ids", []) or []) if my_user else set()

    candidates: dict[int, dict] = {}
    for u in repository.db.users:
        if u.id == me:
            continue
        chats = set(getattr(u, "chat_ids", []) or [])
        if my_chats and not (chats & my_chats):
            continue
        candidates[u.id] = {
            "id": u.id,
            "username": u.username or "",
            "name": _spoken_name(repository, u.id, f"id{u.id}"),
            "shared_chats": list(chats & my_chats) if my_chats else [],
            "played_against": 0,
        }

    # подсветим тех, с кем играл — сортируем выше
    for s in repository.db.tennis_sessions:
        if s.player_a_id == me:
            other = s.player_b_id
        elif s.player_b_id == me:
            other = s.player_a_id
        else:
            continue
        if other in candidates:
            candidates[other]["played_against"] += 1
        else:
            user = next((u for u in repository.db.users if u.id == other), None)
            candidates[other] = {
                "id": other,
                "username": (user.username or "") if user else "",
                "name": _spoken_name(repository, other, f"id{other}"),
                "shared_chats": [],
                "played_against": 1,
            }

    ordered = sorted(
        candidates.values(),
        key=lambda c: (-c["played_against"], (c["username"] or c["name"]).lower()),
    )
    return web.json_response({"opponents": ordered})


async def parse_import(request: web.Request) -> web.Response:
    """POST /api/tennis/import/parse — превью разбора без сохранения.

    {text: "..."} → {entries: [...]} либо {error, line_no?}.
    """
    require_user(request)
    repository: Repository = request.app["repository"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    text = str(body.get("text", ""))
    try:
        entries = parse_bulk_history(text)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    rendered = []
    for entry in entries:
        opp_id = _resolve_user(repository, entry.opponent_raw)
        rendered.append({
            "line_no": entry.line_no,
            "date": entry.date.isoformat(),
            "opponent_raw": entry.opponent_raw,
            "opponent_id": opp_id,
            "opponent_name": (
                _spoken_name(repository, opp_id, entry.opponent_raw) if opp_id else None
            ),
            "mode": entry.mode,
            "wins_a": entry.wins_a,
            "wins_b": entry.wins_b,
            "score_pairs": entry.score_pairs,
        })
    return web.json_response({"entries": rendered})


async def commit_import(request: web.Request) -> web.Response:
    """POST /api/tennis/import — действительно сохраняет.

    {text: "...", chat_id?: int}
    """
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    text = str(body.get("text", ""))
    chat_id = int(body.get("chat_id") or user_id)
    try:
        entries = parse_bulk_history(text)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    # Резолвим всех оппонентов заранее — атомарно
    resolved: list[tuple[BulkEntry, int]] = []
    for entry in entries:
        opp = _resolve_user(repository, entry.opponent_raw)
        if opp is None:
            return web.json_response(
                {"error": f"строка {entry.line_no}: оппонент «{entry.opponent_raw}» не найден"},
                status=400,
            )
        if opp == user_id:
            return web.json_response(
                {"error": f"строка {entry.line_no}: сам с собой играть нельзя"},
                status=400,
            )
        resolved.append((entry, opp))

    created: list[dict] = []
    for entry, opp_id in resolved:
        session = _build_session_from_entry(
            repository, entry, opp_id, initiator_id=user_id, chat_id=chat_id
        )
        repository.db.tennis_sessions.append(session)
        created.append(_serialize_session(repository, session))
    await repository.save()
    return web.json_response({"created": created}, status=201)


def _build_session_from_entry(
    repository: Repository,
    entry: BulkEntry,
    opponent_id: int,
    *,
    initiator_id: int,
    chat_id: int,
) -> TennisSession:
    next_id = max((s.id for s in repository.db.tennis_sessions), default=0) + 1
    if entry.mode == "aggregate":
        matches = aggregate_session_matches(entry.date, entry.wins_a or 0, entry.wins_b or 0)
        return TennisSession(
            id=next_id,
            chat_id=chat_id,
            player_a_id=initiator_id,
            player_b_id=opponent_id,
            started_at=entry.date,
            ended_at=entry.date,
            last_activity_at=entry.date,
            matches=matches,
            is_aggregate_only=True,
            closed_reason="manual",
            initiator_id=initiator_id,
        )
    cur = entry.date
    matches: list[TennisMatch] = []
    for sa, sb in entry.score_pairs:
        matches.append(TennisMatch(
            started_at=cur,
            ended_at=cur,
            winner=SIDE_A if sa > sb else SIDE_B,
            score_a=sa,
            score_b=sb,
        ))
    return TennisSession(
        id=next_id,
        chat_id=chat_id,
        player_a_id=initiator_id,
        player_b_id=opponent_id,
        started_at=entry.date,
        ended_at=entry.date,
        last_activity_at=entry.date,
        matches=matches,
        is_aggregate_only=False,
        closed_reason="manual",
        initiator_id=initiator_id,
    )


async def serve_toggle(request: web.Request) -> web.Response:
    """POST /api/tennis/sessions/{id}/serve — переключить first_server."""
    user_id = require_user(request)
    repository: Repository = request.app["repository"]
    try:
        sid = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad id"}, status=400)
    session = next((s for s in repository.db.tennis_sessions if s.id == sid), None)
    if session is None:
        return web.json_response({"error": "not found"}, status=404)
    if not _user_can_modify(session, user_id):
        return web.json_response({"error": "forbidden"}, status=403)
    if session.ended_at is not None:
        return web.json_response({"error": "session closed"}, status=409)
    session.first_server = SIDE_B if session.first_server == SIDE_A else SIDE_A
    session.last_activity_at = datetime.now()
    await repository.save()
    room = get_manager().get_room(sid)
    if room is not None:
        await room.broadcast()
    return web.json_response(_serialize_session(repository, session, detailed=True))


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/tennis/sessions", list_sessions)
    app.router.add_post("/api/tennis/sessions", create_session)
    app.router.add_get("/api/tennis/sessions/{id}", get_session)
    app.router.add_delete("/api/tennis/sessions/{id}", delete_session)
    app.router.add_post("/api/tennis/sessions/{id}/serve", serve_toggle)
    app.router.add_delete(
        "/api/tennis/sessions/{id}/matches/{idx}", delete_match
    )
    app.router.add_get("/api/tennis/stats", get_stats)
    app.router.add_get("/api/tennis/opponents", list_opponents)
    app.router.add_post("/api/tennis/import/parse", parse_import)
    app.router.add_post("/api/tennis/import", commit_import)
