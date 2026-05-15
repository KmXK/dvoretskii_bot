"""WebSocket-комнаты и live-сессии настольного тенниса.

Сессия — single source of truth, лежит в repository.db.tennis_sessions.
Комната — лёгкая обёртка с активными подключениями. При полном disconnect
комната сохраняется, но без подключений; новые WS-клиенты находят сессию
по user_id и переподключаются. TTL: 1 час неактивности → автозакрытие.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from os import environ
from typing import Callable
from urllib.parse import parse_qsl

from aiohttp import web

from steward.data.models.tennis import TennisMatch, TennisSession
from steward.data.repository import Repository
from steward.tennis.engine import (
    SIDE_A,
    SIDE_B,
    is_valid_party_score,
    server_for_next_point,
    server_progress,
    session_wins,
)
from steward.tennis.tts import (
    match_announcement_text,
    session_end_announcement_text,
    synthesize,
)

logger = logging.getLogger(__name__)

TTL_SECONDS = 60 * 60                # 1 час неактивности → закрываем
TTL_CHECK_INTERVAL = 60              # пробуждаемся раз в минуту
SIDES = (SIDE_A, SIDE_B)


def _iso_utc(dt: datetime | None) -> str | None:
    """Серверные timestamps — naive UTC (Docker UTC). Добавляем Z, чтобы браузер
    не парсил ISO-строку как локальное время (что давало бы офсет в часах)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


def _validate_telegram_init_data(init_data_raw: str) -> dict | None:
    bot_token = environ.get("TELEGRAM_BOT_TOKEN", "")
    if not init_data_raw or not bot_token:
        return None
    try:
        params = dict(parse_qsl(init_data_raw, keep_blank_values=True))
        received_hash = params.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            return None
        user_str = params.get("user")
        return json.loads(user_str) if user_str else None
    except Exception:
        logger.exception("tennis initData validation error")
        return None


# ── Room (light wrapper over a persisted TennisSession) ───────────────────────

class TennisRoom:
    """Связывает сессию из БД с активными WS-подключениями.

    Все мутации идут через TennisRoom.* — они обновляют сессию, сохраняют БД,
    обновляют last_activity_at и рассылают новое состояние.
    """

    def __init__(self, session: TennisSession, repository: Repository, manager: "TennisRoomManager"):
        self.session = session
        self.repository = repository
        self.manager = manager
        self.connections: dict[int, web.WebSocketResponse] = {}

    # ── permissions ──────────────────────────────────────────────────────────

    def can_edit(self, user_id: int) -> bool:
        return user_id in (
            self.session.player_a_id,
            self.session.player_b_id,
            self.session.initiator_id,
        )

    # ── state serialization for frontend ─────────────────────────────────────

    def to_state(self, viewer_id: int | None = None) -> dict:
        wins_a, wins_b = session_wins(self.session)
        server, srv_n, srv_total = server_progress(
            self.session.first_server,
            self.session.current_score_a,
            self.session.current_score_b,
        )
        return {
            "id": self.session.id,
            "chat_id": self.session.chat_id,
            "player_a_id": self.session.player_a_id,
            "player_b_id": self.session.player_b_id,
            "player_a_name": self.manager._spoken_name(self.session.player_a_id, "игрок А"),
            "player_b_name": self.manager._spoken_name(self.session.player_b_id, "игрок Б"),
            "started_at": _iso_utc(self.session.started_at),
            "ended_at": _iso_utc(self.session.ended_at),
            "last_activity_at": _iso_utc(self.session.last_activity_at),
            "is_aggregate_only": self.session.is_aggregate_only,
            "closed_reason": self.session.closed_reason,
            "note": self.session.note,
            "wins": [wins_a, wins_b],
            "current_score": [self.session.current_score_a, self.session.current_score_b],
            "first_server": self.session.first_server,
            "server": server,
            "server_progress": [srv_n, srv_total],
            "set_size": self.session.set_size,
            "matches": [
                {
                    "started_at": _iso_utc(m.started_at),
                    "ended_at": _iso_utc(m.ended_at),
                    "winner": m.winner,
                    "score_a": m.score_a,
                    "score_b": m.score_b,
                }
                for m in self.session.matches
            ],
            "permissions": {
                "can_edit": self.can_edit(viewer_id) if viewer_id is not None else False,
            },
        }

    # ── mutations ────────────────────────────────────────────────────────────

    async def record_point(self, side: str) -> tuple[bool, str, dict]:
        """Записать поинт. Если партия завершается — фиксируем её, ротация подачи.

        Возвращает (ok, error, info) где info = {"match_completed": bool, "set_completed": bool}.
        """
        if self.session.ended_at is not None:
            return False, "Сессия уже закрыта", {}
        if side not in SIDES:
            return False, "Неизвестная сторона", {}

        if side == SIDE_A:
            self.session.current_score_a += 1
        else:
            self.session.current_score_b += 1
        self.session.points_log.append(side)

        info = {"match_completed": False, "set_completed": False}
        completed_match: TennisMatch | None = None

        if is_valid_party_score(self.session.current_score_a, self.session.current_score_b):
            now = datetime.now()
            prev_end = self._latest_match_end() or self.session.started_at
            winner = SIDE_A if self.session.current_score_a > self.session.current_score_b else SIDE_B
            completed_match = TennisMatch(
                started_at=prev_end,
                ended_at=now,
                winner=winner,
                score_a=self.session.current_score_a,
                score_b=self.session.current_score_b,
            )
            self.session.matches.append(completed_match)
            # Сброс live-состояния под следующую партию + ротация первой подачи
            self.session.current_score_a = 0
            self.session.current_score_b = 0
            self.session.points_log = []
            self.session.first_server = SIDE_B if self.session.first_server == SIDE_A else SIDE_A
            info["match_completed"] = True

            # Граница сета — анонсируем, если последний из «sets_announced» сетов ещё впереди
            if self.session.set_size > 0:
                completed_sets = len(self.session.matches) // self.session.set_size
                if completed_sets > self.session.sets_announced:
                    self.session.sets_announced = completed_sets
                    info["set_completed"] = True

        self.session.last_activity_at = datetime.now()
        await self.repository.save()

        if completed_match is not None:
            asyncio.create_task(self.manager._announce_match(self.session, completed_match))
        if info["set_completed"]:
            asyncio.create_task(self.manager._announce_set_end(self.session))

        return True, "", info

    async def undo_point(self) -> tuple[bool, str]:
        """Откат: если есть поинты в текущей партии — убираем последний.
        Если текущая 0:0 и есть записанные партии — откатываем последнюю партию.
        """
        if self.session.ended_at is not None:
            return False, "Сессия уже закрыта"

        if self.session.points_log:
            last_side = self.session.points_log.pop()
            if last_side == SIDE_A:
                self.session.current_score_a = max(0, self.session.current_score_a - 1)
            else:
                self.session.current_score_b = max(0, self.session.current_score_b - 1)
            self.session.last_activity_at = datetime.now()
            await self.repository.save()
            return True, ""

        if self.session.matches:
            removed = self.session.matches.pop()
            # Возвращаем счёт партии в live, чтобы можно было доиграть/пересохранить
            self.session.current_score_a = removed.score_a or 0
            self.session.current_score_b = removed.score_b or 0
            # «Размотать» один поинт, чтобы счёт был «11:7 → 11:6» (рукоятка для исправления)
            if self.session.current_score_a > 0 and self.session.current_score_a > self.session.current_score_b:
                self.session.current_score_a -= 1
                self.session.points_log = [SIDE_A] * self.session.current_score_a + [SIDE_B] * self.session.current_score_b
            elif self.session.current_score_b > 0:
                self.session.current_score_b -= 1
                self.session.points_log = [SIDE_A] * self.session.current_score_a + [SIDE_B] * self.session.current_score_b
            # Возвращаем first_server, который был в этой партии (предыдущий)
            self.session.first_server = SIDE_B if self.session.first_server == SIDE_A else SIDE_A
            # Откатываем счётчик анонсированных сетов
            if self.session.set_size > 0:
                self.session.sets_announced = min(
                    self.session.sets_announced,
                    len(self.session.matches) // self.session.set_size,
                )
            self.session.last_activity_at = datetime.now()
            await self.repository.save()
            return True, ""

        return False, "Нечего отменять"

    async def close(self, reason: str = "manual") -> None:
        if self.session.ended_at is not None:
            return
        now = datetime.now()
        self.session.ended_at = now
        self.session.last_activity_at = now
        self.session.closed_reason = reason
        await self.repository.save()
        asyncio.create_task(self.manager._announce_session_end(self.session, reason))

    def _latest_match_end(self) -> datetime | None:
        latest: datetime | None = None
        for m in self.session.matches:
            ts = m.ended_at or m.started_at
            if latest is None or ts > latest:
                latest = ts
        return latest

    # ── broadcast ────────────────────────────────────────────────────────────

    async def broadcast(self, type_: str = "state", **extra) -> None:
        for uid, ws in list(self.connections.items()):
            payload = {"type": type_, "state": self.to_state(uid), **extra}
            try:
                await ws.send_str(json.dumps(payload, ensure_ascii=False))
            except Exception:
                logger.exception("tennis broadcast failed uid=%s", uid)


# ── RoomManager ──────────────────────────────────────────────────────────────

class TennisRoomManager:
    def __init__(self):
        self.rooms: dict[int, TennisRoom] = {}        # session_id → room
        self._ttl_task: asyncio.Task | None = None
        self._bot = None                              # ExtBot для уведомлений
        self._user_display: Callable[[int], str] | None = None

    def configure_notifications(self, bot, user_display: Callable[[int], str]) -> None:
        """Бот для отправки уведомлений по таймауту + способ отрендерить имя игрока."""
        self._bot = bot
        self._user_display = user_display

    def get_room(self, session_id: int) -> TennisRoom | None:
        return self.rooms.get(session_id)

    def attach(self, session: TennisSession, repository: Repository) -> TennisRoom:
        existing = self.rooms.get(session.id)
        if existing is not None:
            existing.session = session  # на случай горячей перезагрузки модели
            return existing
        room = TennisRoom(session, repository, self)
        self.rooms[session.id] = room
        return room

    def detach(self, session_id: int) -> None:
        self.rooms.pop(session_id, None)

    def find_active_for_user(
        self,
        repository: Repository,
        user_id: int,
        chat_id: int | None = None,
    ) -> TennisRoom | None:
        """Активная сессия, где пользователь — игрок или инициатор."""
        for session in repository.db.tennis_sessions:
            if session.ended_at is not None:
                continue
            if chat_id is not None and session.chat_id != chat_id:
                continue
            if user_id in (session.player_a_id, session.player_b_id, session.initiator_id):
                return self.attach(session, repository)
        return None

    # ── TTL watcher ──────────────────────────────────────────────────────────

    def start_ttl_watcher(self, repository: Repository) -> None:
        if self._ttl_task and not self._ttl_task.done():
            return
        self._ttl_task = asyncio.create_task(self._ttl_loop(repository))

    async def _ttl_loop(self, repository: Repository) -> None:
        try:
            while True:
                await asyncio.sleep(TTL_CHECK_INTERVAL)
                await self._sweep_once(repository)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("tennis TTL loop crashed")

    async def _sweep_once(self, repository: Repository) -> None:
        now = datetime.now()
        cutoff = now - timedelta(seconds=TTL_SECONDS)
        for session in list(repository.db.tennis_sessions):
            if session.ended_at is not None:
                continue
            if session.last_activity_at > cutoff:
                continue
            room = self.attach(session, repository)
            await room.close(reason="timeout")
            await room.broadcast("closed", reason="timeout")
            await self._notify_timeout(session)

    async def _notify_timeout(self, session: TennisSession) -> None:
        if self._bot is None:
            return
        wins_a, wins_b = session_wins(session)
        name_a = self._display(session.player_a_id)
        name_b = self._display(session.player_b_id)
        text = (
            f"⏱ Сессия тенниса #{session.id} закрыта по таймауту.\n"
            f"Итог: {name_a} {wins_a} : {wins_b} {name_b}"
        )
        try:
            await self._bot.send_message(chat_id=session.chat_id, text=text)
        except Exception:
            logger.exception("tennis timeout notification failed for session=%s", session.id)

    def _display(self, user_id: int) -> str:
        if self._user_display is None:
            return str(user_id)
        try:
            return self._user_display(user_id)
        except Exception:
            return str(user_id)

    def _spoken_name(self, user_id: int, fallback: str) -> str:
        raw = self._display(user_id)
        if not raw or raw.startswith("id"):
            return fallback
        return raw.lstrip("@")

    async def _announce_match(self, session: TennisSession, match: TennisMatch) -> None:
        if self._bot is None:
            return
        try:
            winner_id = session.player_a_id if match.winner == SIDE_A else session.player_b_id
            fallback = "игрок А" if match.winner == SIDE_A else "игрок Б"
            name = self._spoken_name(winner_id, fallback)
            text = match_announcement_text(match, name)
            audio = await synthesize(text)
            if not audio:
                return
            await self._bot.send_voice(
                chat_id=session.chat_id,
                voice=audio,
                caption=text,
            )
        except Exception:
            logger.exception("tennis match announce failed for session=%s", session.id)

    async def _announce_set_end(self, session: TennisSession) -> None:
        if self._bot is None or session.set_size <= 0:
            return
        try:
            wins_a, wins_b = session_wins(session)
            name_a = self._spoken_name(session.player_a_id, "игрок А")
            name_b = self._spoken_name(session.player_b_id, "игрок Б")
            set_num = session.sets_announced
            text = (
                f"Конец сета {set_num}. "
                f"{name_a} — {wins_a} партий, {name_b} — {wins_b} партий."
            )
            audio = await synthesize(text)
            if not audio:
                return
            await self._bot.send_voice(
                chat_id=session.chat_id,
                voice=audio,
                caption=text,
            )
        except Exception:
            logger.exception("tennis set-end announce failed for session=%s", session.id)

    async def _announce_session_end(self, session: TennisSession, reason: str) -> None:
        if self._bot is None:
            return
        # Аггрегатные импорты и таймаут без активности — без голоса
        if session.is_aggregate_only or reason == "timeout":
            return
        try:
            name_a = self._spoken_name(session.player_a_id, "игрок А")
            name_b = self._spoken_name(session.player_b_id, "игрок Б")
            text = session_end_announcement_text(session, name_a, name_b)
            audio = await synthesize(text)
            if not audio:
                return
            await self._bot.send_voice(
                chat_id=session.chat_id,
                voice=audio,
                caption=text,
            )
        except Exception:
            logger.exception("tennis session-end announce failed for session=%s", session.id)


_manager = TennisRoomManager()


def get_manager() -> TennisRoomManager:
    return _manager


# ── WS handler ───────────────────────────────────────────────────────────────

async def tennis_ws_handler(request: web.Request):
    """Single endpoint: /ws/tennis. Один клиент = одно подключение к одной сессии.

    Протокол:
      client → {"type": "hello", "init_data": "..."}    — авторизация
      client → {"type": "point", "side": "a"|"b"}       — поинт; партия закроется автоматически
      client → {"type": "undo"}                          — откат поинта; если 0:0 — откат партии
      client → {"type": "close"}
      server → {"type": "state", "state": {...}}        — на любое изменение
      server → {"type": "closed", "reason": "manual"|"timeout", "state": {...}}
      server → {"type": "error", "message": "..."}
      server → {"type": "no_active"}                    — нет активной сессии для юзера
    """
    from steward.api.auth import ws_session_user

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    repository: Repository = request.app["repository"]
    user_id: int | None = None
    current_room: TennisRoom | None = None

    async def _send(payload: dict) -> None:
        try:
            await ws.send_str(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    async def _attach_for(uid: int) -> None:
        """Связать соединение с активной сессией пользователя (если есть)."""
        nonlocal current_room
        room = _manager.find_active_for_user(repository, uid)
        if room is None:
            await _send({"type": "no_active"})
            return
        current_room = room
        room.connections[uid] = ws
        await _send({"type": "state", "state": room.to_state(uid)})

    # 1) Cookie/header-аутентификация (выставляется AuthContext через /api/auth/webapp).
    #    Работает и в браузере, и в Telegram WebApp после первой инициализации.
    cookie_auth = ws_session_user(request)
    if cookie_auth:
        user_id = cookie_auth[0]
        await _attach_for(user_id)

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                if msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
                continue

            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            t = data.get("type")

            if t == "hello":
                # Если cookie-сессия уже сработала — игнорируем повторную авторизацию
                if user_id is not None:
                    await _send({"type": "ok"})
                    continue
                init_data_raw = str(data.get("init_data", ""))
                tg_user = _validate_telegram_init_data(init_data_raw)
                if not tg_user or not tg_user.get("id"):
                    await _send({"type": "error", "message": "Invalid Telegram auth"})
                    continue
                user_id = int(tg_user["id"])
                await _attach_for(user_id)

            elif t == "point":
                if current_room is None or user_id is None:
                    await _send({"type": "error", "message": "Not authed"})
                    continue
                if not current_room.can_edit(user_id):
                    await _send({"type": "error", "message": "Только игроки могут писать счёт"})
                    continue
                side = str(data.get("side", ""))
                ok, err, _info = await current_room.record_point(side)
                if not ok:
                    await _send({"type": "error", "message": err})
                    continue
                await current_room.broadcast()

            elif t == "undo":
                if current_room is None or user_id is None:
                    await _send({"type": "error", "message": "Not authed"})
                    continue
                if not current_room.can_edit(user_id):
                    await _send({"type": "error", "message": "Только игроки могут отменять"})
                    continue
                ok, err = await current_room.undo_point()
                if not ok:
                    await _send({"type": "error", "message": err})
                    continue
                await current_room.broadcast()

            elif t == "close":
                if current_room is None or user_id is None:
                    await _send({"type": "error", "message": "Not authed"})
                    continue
                if not current_room.can_edit(user_id):
                    await _send({"type": "error", "message": "Только игроки могут закрыть сессию"})
                    continue
                await current_room.close("manual")
                await current_room.broadcast("closed", reason="manual")

    except Exception:
        logger.exception("tennis ws error uid=%s", user_id)
    finally:
        if current_room is not None and user_id is not None:
            current_room.connections.pop(user_id, None)
            # комнату не удаляем — сессия живёт, пока не закрыта; даём шанс на reconnect

    return ws
