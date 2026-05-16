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
    session_wins,
)
from steward.tennis.commentator import generate_match_commentary
from steward.tennis.tts import (
    match_announcement_text,
    session_end_announcement_text,
    synthesize,
)

logger = logging.getLogger(__name__)

TTL_SECONDS = 60 * 60                # 1 час неактивности → закрываем
TTL_CHECK_INTERVAL = 60              # пробуждаемся раз в минуту
MATCH_EDIT_WINDOW_SEC = 60 * 60       # 1 час после закрытия — можно ещё редактировать партии
SIDES = (SIDE_A, SIDE_B)


def can_edit_matches(session: TennisSession, *, now: datetime | None = None) -> bool:
    """Открыта ли возможность редактировать/удалять партии сессии.

    Активная сессия → да. Закрытая → да в течение часа после ended_at.
    """
    if session.ended_at is None:
        return True
    cur = now or datetime.now()
    return (cur - session.ended_at).total_seconds() < MATCH_EDIT_WINDOW_SEC


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
        # Текст последней озвучки/коммента — фронт играет его через speak()
        # вместо стандартной «Партия! Победил X. Счёт 11:7». In-memory, не
        # сохраняется в БД.
        self.last_commentary: str = ""
        self.last_commentary_seq: int = 0  # счётчик для фронта чтобы не повторять

    # ── permissions ──────────────────────────────────────────────────────────

    def can_edit(self, user_id: int) -> bool:
        """Кто может закрыть сессию / делать административные действия."""
        return user_id in (
            self.session.player_a_id,
            self.session.player_b_id,
            self.session.initiator_id,
        )

    def is_player(self, user_id: int) -> bool:
        """Кто может писать/править счёт партий — только участники игры."""
        return user_id in (self.session.player_a_id, self.session.player_b_id)

    # ── state serialization for frontend ─────────────────────────────────────

    def to_state(self, viewer_id: int | None = None) -> dict:
        wins_a, wins_b = session_wins(self.session)
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
            "first_server": self.session.first_server,
            "serve_streak": self.session.serve_streak,
            "last_commentary": self.last_commentary,
            "last_commentary_seq": self.last_commentary_seq,
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

    async def record_match_with_score(
        self, score_a: int, score_b: int
    ) -> tuple[bool, str, dict]:
        """Записать партию готовым счётом (быстрый финиш без point-by-point)."""
        if self.session.ended_at is not None:
            return False, "Сессия уже закрыта", {}
        if not is_valid_party_score(score_a, score_b):
            return False, "Невалидный счёт партии (11 + разница ≥2)", {}

        now = datetime.now()
        prev_end = self._latest_match_end() or self.session.started_at
        winner = SIDE_A if score_a > score_b else SIDE_B
        match = TennisMatch(
            started_at=prev_end,
            ended_at=now,
            winner=winner,
            score_a=score_a,
            score_b=score_b,
        )
        self.session.matches.append(match)
        # Первая подача переключается каждые serve_streak партий
        streak = max(1, self.session.serve_streak or 2)
        if len(self.session.matches) % streak == 0:
            self.session.first_server = SIDE_B if self.session.first_server == SIDE_A else SIDE_A

        info = {"match_completed": True}
        self.session.last_activity_at = datetime.now()
        await self.repository.save()

        asyncio.create_task(self.manager._announce_match(self.session, match))
        return True, "", info

    async def update_match(
        self, idx: int, score_a: int, score_b: int
    ) -> tuple[bool, str]:
        """Поменять счёт уже записанной партии. Победитель меняется автоматом
        если этого требует новый счёт.
        """
        if not can_edit_matches(self.session):
            return False, "Окно редактирования закрыто (1 час после конца сессии)"
        if idx < 0 or idx >= len(self.session.matches):
            return False, "Неверный индекс партии"
        if not is_valid_party_score(score_a, score_b):
            return False, "Невалидный счёт партии (11 + разница ≥2)"
        m = self.session.matches[idx]
        m.score_a = score_a
        m.score_b = score_b
        m.winner = SIDE_A if score_a > score_b else SIDE_B
        self.session.last_activity_at = datetime.now()
        await self.repository.save()
        return True, ""

    async def undo_last_match(self) -> tuple[bool, str]:
        """Откат последней записанной партии. Возвращает first_server обратно
        если по правилу serve_streak подача переключилась после неё."""
        if self.session.ended_at is not None:
            return False, "Сессия уже закрыта"
        if not self.session.matches:
            return False, "Нечего отменять"
        # До отката: матчей было N → подача переключилась если N % streak == 0
        streak = max(1, self.session.serve_streak or 2)
        if len(self.session.matches) % streak == 0:
            self.session.first_server = SIDE_B if self.session.first_server == SIDE_A else SIDE_A
        self.session.matches.pop()
        self.session.last_activity_at = datetime.now()
        await self.repository.save()
        return True, ""

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
        """Имя, пригодное для произношения. Логику диктует feature через
        configure_notifications(user_display=...). По умолчанию — фоллбек."""
        if self._user_display is None:
            return fallback
        try:
            raw = (self._user_display(user_id) or "").strip()
        except Exception:
            return fallback
        if not raw or raw.startswith("id"):
            return fallback
        return raw.lstrip("@")

    def _anyone_in_webapp(self, session: TennisSession) -> bool:
        """Подключён ли кто-то из игроков прямо сейчас к WS-комнате.

        Если да — озвучку в чат не дублируем: они и так услышат её в вебаппе.
        """
        room = self.rooms.get(session.id)
        if room is None or not room.connections:
            return False
        for uid in room.connections:
            if uid in (session.player_a_id, session.player_b_id, session.initiator_id):
                return True
        return False

    async def _announce_match(self, session: TennisSession, match: TennisMatch) -> None:
        """После записанной партии: генерим живой комментарий (AI),
        кладём в room.last_commentary (фронт играет в вебе), и шлём voice
        в чат если в вебе никого нет.
        """
        name_a = self._spoken_name(session.player_a_id, "игрок А")
        name_b = self._spoken_name(session.player_b_id, "игрок Б")

        commentary = await generate_match_commentary(
            session, match, name_a=name_a, name_b=name_b
        )
        winner_name = name_a if match.winner == SIDE_A else name_b
        text = commentary or match_announcement_text(match, winner_name)

        # Обновим in-memory state и разошлём
        room = self.rooms.get(session.id)
        if room is not None:
            room.last_commentary = text
            room.last_commentary_seq += 1
            try:
                await room.broadcast()
            except Exception:
                logger.exception("tennis broadcast after commentary failed")

        if self._bot is None:
            return
        if self._anyone_in_webapp(session):
            return  # игроки в вебе — пусть слушают коммент там, не дублируем в чат
        try:
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
      client → {"type": "finish_party", "score_a": int, "score_b": int} — записать партию счётом
      client → {"type": "edit_match", "idx": int, "score_a": int, "score_b": int} — исправить
      client → {"type": "undo"}                          — откат последней партии
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

            elif t == "finish_party":
                if current_room is None or user_id is None:
                    await _send({"type": "error", "message": "Not authed"})
                    continue
                if not current_room.is_player(user_id):
                    await _send({"type": "error", "message": "Только участники игры могут писать счёт"})
                    continue
                raw_a = data.get("score_a")
                raw_b = data.get("score_b")
                if not isinstance(raw_a, (int, float)) or not isinstance(raw_b, (int, float)):
                    await _send({"type": "error", "message": "Нужны оба числа"})
                    continue
                ok, err, _info = await current_room.record_match_with_score(int(raw_a), int(raw_b))
                if not ok:
                    await _send({"type": "error", "message": err})
                    continue
                await current_room.broadcast()

            elif t == "edit_match":
                if current_room is None or user_id is None:
                    await _send({"type": "error", "message": "Not authed"})
                    continue
                if not current_room.is_player(user_id):
                    await _send({"type": "error", "message": "Править счёт могут только участники игры"})
                    continue
                try:
                    idx = int(data.get("idx"))
                    score_a = int(data.get("score_a"))
                    score_b = int(data.get("score_b"))
                except (TypeError, ValueError):
                    await _send({"type": "error", "message": "Параметры edit_match невалидны"})
                    continue
                ok, err = await current_room.update_match(idx, score_a, score_b)
                if not ok:
                    await _send({"type": "error", "message": err})
                    continue
                await current_room.broadcast()

            elif t == "undo":
                if current_room is None or user_id is None:
                    await _send({"type": "error", "message": "Not authed"})
                    continue
                if not current_room.is_player(user_id):
                    await _send({"type": "error", "message": "Отменять может только участник игры"})
                    continue
                ok, err = await current_room.undo_last_match()
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
