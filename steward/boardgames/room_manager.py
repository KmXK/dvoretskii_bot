import asyncio
import hashlib
import hmac
import json
import logging
import random
import uuid
from dataclasses import dataclass
from os import environ
from typing import NotRequired, TypedDict
from urllib.parse import parse_qsl

import chess
from aiohttp import web

from steward.boardgames import chess_logic, checkers_logic
from steward.data.models.user import User
from steward.data.repository import Repository

logger = logging.getLogger(__name__)

MONKEY_CHIP_RATE = 10
MAX_ROOMS = 200
MAX_BET = 200
ALLOWED_BETS = {5, 10, 25, 50, 100, 200}
BOT_MOVE_DELAY = (0.6, 1.4)

GAME_CHESS = "chess"
GAME_CHECKERS = "checkers"
ALLOWED_GAMES = {GAME_CHESS, GAME_CHECKERS}
ALLOWED_SIDES = {"white", "black"}


class AuthPayload(TypedDict):
    type: str
    initData: str


class CreateRoomPayload(TypedDict):
    type: str
    gameType: NotRequired[str]
    stake: NotRequired[int | str]
    botEnabled: NotRequired[bool]
    botSide: NotRequired[str]
    botDifficulty: NotRequired[str]
    name: NotRequired[str]


class JoinRoomPayload(TypedDict):
    type: str
    roomId: str
    side: NotRequired[str]


class MovePayload(TypedDict):
    type: str
    move: NotRequired[str]
    from_: NotRequired[list[int]]
    to: NotRequired[list[int]]


class BetPayload(TypedDict):
    type: str
    side: str
    amount: int | str


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_auth_payload(data: dict) -> bool:
    return isinstance(data.get("initData"), str)


def _is_create_room_payload(data: dict) -> bool:
    return data.get("type") == "create_room"


def _is_join_room_payload(data: dict) -> bool:
    return isinstance(data.get("roomId"), str) and data.get("roomId", "").strip() != ""


def _is_move_payload(data: dict) -> bool:
    if isinstance(data.get("move"), str):
        return True
    fr = data.get("from")
    to = data.get("to")
    return isinstance(fr, list) and isinstance(to, list)


def _is_bet_payload(data: dict) -> bool:
    return isinstance(data.get("side"), str) and ("amount" in data)


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
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        user_str = params.get("user")
        if user_str:
            return json.loads(user_str)
        return None
    except Exception:
        logger.exception("boardgames initData validation error")
        return None


def _find_user(repository: Repository, user_id: int) -> User | None:
    return next((u for u in repository.db.users if u.id == user_id), None)


def _get_or_create_user(repository: Repository, user_id: int, username: str = "") -> User:
    user = _find_user(repository, user_id)
    if user is None:
        user = User(user_id, username or None)
        repository.db.users.append(user)
    return user


@dataclass
class BoardBet:
    user_id: int
    user_name: str
    side: str
    amount: int


@dataclass
class RoomState:
    room_id: str
    name: str
    game_type: str
    creator_id: int
    started: bool
    finished: bool
    winner: str | None
    player_count: int
    spectator_count: int
    stake: int
    bot_side: str | None
    bot_difficulty: str
    players: list[dict]

    def to_dict(self) -> dict:
        return {
            "id": self.room_id,
            "name": self.name,
            "gameType": self.game_type,
            "creatorId": self.creator_id,
            "started": self.started,
            "finished": self.finished,
            "winner": self.winner,
            "playerCount": self.player_count,
            "spectatorCount": self.spectator_count,
            "stake": self.stake,
            "botSide": self.bot_side,
            "botDifficulty": self.bot_difficulty,
            "players": self.players,
        }


@dataclass
class GameState:
    room: dict
    role: str
    turn: str
    started: bool
    finished: bool
    winner: str | None
    last_move: dict | None
    board: dict
    legal_moves: list
    bets: list[dict]

    def to_dict(self) -> dict:
        return {
            "room": self.room,
            "role": self.role,
            "turn": self.turn,
            "started": self.started,
            "finished": self.finished,
            "winner": self.winner,
            "lastMove": self.last_move,
            "board": self.board,
            "legalMoves": self.legal_moves,
            "bets": self.bets,
        }


class BoardRoom:
    def __init__(
        self,
        room_id: str,
        name: str,
        game_type: str,
        creator_id: int,
        creator_name: str,
        stake: int = 0,
        bot_side: str | None = None,
        bot_difficulty: str = chess_logic.BOT_MEDIUM,
    ):
        self.id = room_id
        self.name = name
        self.game_type = game_type
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.stake = stake
        self.bot_side = bot_side if bot_side in ALLOWED_SIDES else None
        self.bot_difficulty = (
            bot_difficulty
            if bot_difficulty in chess_logic.BOT_DIFFICULTIES
            else chess_logic.BOT_MEDIUM
        )

        self.connections: dict[int, web.WebSocketResponse] = {}
        self.player_names: dict[int, str] = {}
        self.spectators: set[int] = set()
        self.players: dict[str, int | None] = {"white": None, "black": None}

        self.started = False
        self.finished = False
        self.winner: str | None = None
        self.turn: str = "white"
        self.last_move: dict | None = None

        self.bets: dict[int, BoardBet] = {}
        self.stake_locked: set[int] = set()

        self.chess_board: chess.Board | None = None
        self.checkers_board: list[list[str]] | None = None
        self.checkers_forced_from: list[int] | None = None
        self._bot_task: asyncio.Task | None = None

    def _public_players(self) -> list[dict]:
        out = []
        for side in ("white", "black"):
            uid = self.players.get(side)
            if uid is None:
                if self.bot_side == side:
                    out.append({"side": side, "id": 0, "name": "🤖 Bot", "isBot": True})
                continue
            out.append({
                "side": side,
                "id": uid,
                "name": self.player_names.get(uid, str(uid)),
                "isBot": False,
            })
        return out

    def to_dict(self) -> dict:
        return RoomState(
            room_id=self.id,
            name=self.name,
            game_type=self.game_type,
            creator_id=self.creator_id,
            started=self.started,
            finished=self.finished,
            winner=self.winner,
            player_count=len([p for p in self.players.values() if p is not None]) + (1 if self.bot_side else 0),
            spectator_count=len(self.spectators),
            stake=self.stake,
            bot_side=self.bot_side,
            bot_difficulty=self.bot_difficulty,
            players=self._public_players(),
        ).to_dict()

    def _viewer_role(self, uid: int) -> str:
        for side in ("white", "black"):
            if self.players.get(side) == uid:
                return side
        return "spectator"

    def _serialize_board(self) -> dict:
        if self.game_type == GAME_CHESS:
            assert self.chess_board is not None
            return {
                "fen": self.chess_board.fen(),
                "moves": [m.uci() for m in chess_logic.legal_moves(self.chess_board)],
            }
        assert self.checkers_board is not None
        return {
            "grid": self.checkers_board,
            "moves": checkers_logic.legal_moves(self.checkers_board, self.turn, self.checkers_forced_from),
            "forcedFrom": self.checkers_forced_from,
        }

    def _legal_moves_for_uid(self, uid: int) -> list:
        role = self._viewer_role(uid)
        if role not in ALLOWED_SIDES:
            return []
        if role != self.turn or not self.started or self.finished:
            return []
        if self.game_type == GAME_CHESS:
            assert self.chess_board is not None
            return [m.uci() for m in chess_logic.legal_moves(self.chess_board)]
        assert self.checkers_board is not None
        return checkers_logic.legal_moves(self.checkers_board, self.turn, self.checkers_forced_from)

    def state_for(self, uid: int) -> dict:
        role = self._viewer_role(uid)
        return GameState(
            room=self.to_dict(),
            role=role,
            turn=self.turn,
            started=self.started,
            finished=self.finished,
            winner=self.winner,
            last_move=self.last_move,
            board=self._serialize_board(),
            legal_moves=self._legal_moves_for_uid(uid),
            bets=[
                {
                    "userId": b.user_id,
                    "userName": b.user_name,
                    "side": b.side,
                    "amount": b.amount,
                }
                for b in self.bets.values()
            ],
        ).to_dict()

    async def broadcast(self, msg: dict) -> set[int]:
        payload = json.dumps(msg, ensure_ascii=False)
        dead_uids: set[int] = set()
        for uid, ws in list(self.connections.items()):
            try:
                await ws.send_str(payload)
            except Exception:
                dead_uids.add(uid)
        return dead_uids

    async def send_states(self) -> set[int]:
        dead_uids: set[int] = set()
        for uid, ws in list(self.connections.items()):
            try:
                st = self.state_for(uid)
                await ws.send_str(json.dumps({"type": "room_state", "state": st}, ensure_ascii=False))
            except Exception:
                dead_uids.add(uid)
        return dead_uids

    def _toggle_turn(self):
        self.turn = "black" if self.turn == "white" else "white"

    def _check_winner_after_move(self) -> str | None:
        if self.game_type == GAME_CHESS:
            assert self.chess_board is not None
            if self.chess_board.is_checkmate():
                return "black" if self.turn == "white" else "white"
            if self.chess_board.is_stalemate() or self.chess_board.is_insufficient_material():
                return "draw"
            return None
        assert self.checkers_board is not None
        if checkers_logic.count_side(self.checkers_board, self.turn) == 0:
            return "black" if self.turn == "white" else "white"
        moves = checkers_logic.legal_moves(self.checkers_board, self.turn)
        if moves:
            return None
        return "black" if self.turn == "white" else "white"

    def _finalize_turn(self):
        self.checkers_forced_from = None
        self._toggle_turn()
        winner = self._check_winner_after_move()
        if winner is not None:
            self.finished = True
            self.winner = winner

    def _apply_checkers_move(self, side: str, mv: dict, is_bot: bool = False) -> bool:
        assert self.checkers_board is not None
        self.checkers_board, piece = checkers_logic.apply_move(self.checkers_board, mv)
        self.last_move = {
            "by": side,
            "from": mv["from"],
            "to": mv["to"],
            "captures": mv["captures"],
            "piece": piece,
        }
        if is_bot:
            self.last_move["bot"] = True

        if mv["captures"]:
            next_caps = checkers_logic.captures_from(
                self.checkers_board,
                mv["to"][0],
                mv["to"][1],
                piece,
                side,
            )
            if next_caps:
                self.checkers_forced_from = [mv["to"][0], mv["to"][1]]
                self.last_move["continue"] = True
                return True
        self._finalize_turn()
        return False

    def start_game(self) -> bool:
        if self.started:
            return False
        white_uid = self.players.get("white")
        black_uid = self.players.get("black")
        if white_uid is None and self.bot_side != "white":
            return False
        if black_uid is None and self.bot_side != "black":
            return False
        if self.game_type == GAME_CHESS:
            self.chess_board = chess_logic.new_board()
            self.checkers_board = None
        else:
            self.checkers_board = checkers_logic.new_board()
            self.chess_board = None
        self.turn = "white"
        self.started = True
        self.finished = False
        self.winner = None
        self.last_move = None
        self.checkers_forced_from = None
        return True

    def make_move(self, uid: int, move_data: dict) -> tuple[bool, str]:
        if not self.started or self.finished:
            return False, "Game is not active"
        side = self._viewer_role(uid)
        if side not in ALLOWED_SIDES:
            return False, "Spectators cannot move"
        if side != self.turn:
            return False, "Not your turn"

        if self.game_type == GAME_CHESS:
            assert self.chess_board is not None
            move_uci = str(move_data.get("move", "")).strip().lower()
            if not move_uci:
                return False, "Move required"
            try:
                mv = chess.Move.from_uci(move_uci)
            except ValueError:
                return False, "Invalid move"
            if mv not in self.chess_board.legal_moves:
                return False, "Illegal move"
            self.chess_board.push(mv)
            self.last_move = {"by": side, "move": move_uci}
        else:
            assert self.checkers_board is not None
            fr = move_data.get("from")
            to = move_data.get("to")
            if not isinstance(fr, list) or not isinstance(to, list) or len(fr) != 2 or len(to) != 2:
                return False, "Invalid move payload"
            legal = checkers_logic.legal_moves(self.checkers_board, side, self.checkers_forced_from)
            picked = next((m for m in legal if m["from"] == fr and m["to"] == to), None)
            if picked is None:
                return False, "Illegal move"
            still_forced = self._apply_checkers_move(side, picked)
            if still_forced:
                return True, "ok"

        if self.game_type == GAME_CHESS:
            self._finalize_turn()
        return True, "ok"

    def cancel_tasks(self):
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()


class BoardRoomManager:
    def __init__(self):
        self.rooms: dict[str, BoardRoom] = {}
        self.player_rooms: dict[int, str] = {}
        self.lobby_connections: dict[int, web.WebSocketResponse] = {}

    def get_room(self, room_id: str) -> BoardRoom | None:
        return self.rooms.get(room_id)

    def list_rooms(self) -> list[dict]:
        return [r.to_dict() for r in self.rooms.values()]

    async def broadcast_rooms(self):
        payload = json.dumps({"type": "rooms_list", "rooms": self.list_rooms()}, ensure_ascii=False)
        dead_uids: set[int] = set()
        for uid, ws in list(self.lobby_connections.items()):
            try:
                await ws.send_str(payload)
            except Exception:
                dead_uids.add(uid)
        for uid in dead_uids:
            self.lobby_connections.pop(uid, None)

    def create_room(
        self,
        name: str,
        game_type: str,
        creator_id: int,
        creator_name: str,
        stake: int,
        bot_side: str | None,
        bot_difficulty: str,
    ) -> BoardRoom:
        if len(self.rooms) >= MAX_ROOMS:
            self.rooms.pop(next(iter(self.rooms)))
        rid = uuid.uuid4().hex[:8]
        room = BoardRoom(
            rid,
            name,
            game_type,
            creator_id,
            creator_name,
            stake,
            bot_side,
            bot_difficulty,
        )
        self.rooms[rid] = room
        return room

    def cleanup_room(self, room_id: str):
        room = self.rooms.get(room_id)
        if room is None:
            return
        room.cancel_tasks()
        del self.rooms[room_id]


_manager = BoardRoomManager()


def _remove_uid_from_room(room: BoardRoom, uid: int):
    room.connections.pop(uid, None)
    room.spectators.discard(uid)
    room.player_names.pop(uid, None)
    for side in ("white", "black"):
        if room.players.get(side) == uid:
            room.players[side] = None


def _cleanup_dead_room_connections(room: BoardRoom):
    stale = [uid for uid, ws in room.connections.items() if ws.closed]
    for uid in stale:
        _remove_uid_from_room(room, uid)
        _manager.player_rooms.pop(uid, None)


def _player_can_join(room: BoardRoom, side: str) -> bool:
    if side not in ALLOWED_SIDES:
        return False
    if room.bot_side == side:
        return False
    return room.players.get(side) is None


def _resolve_join_side(room: BoardRoom, requested: str | None) -> str:
    if room.started:
        return "spectator"
    if requested in ALLOWED_SIDES and _player_can_join(room, requested):
        return requested
    for side in ("white", "black"):
        if _player_can_join(room, side):
            return side
    return "spectator"


def _charge_monkeys(repository: Repository, uid: int, user_name: str, amount: int) -> tuple[bool, int]:
    if amount <= 0:
        user = _get_or_create_user(repository, uid, user_name)
        return True, user.monkeys
    user = _get_or_create_user(repository, uid, user_name)
    if user.monkeys < amount:
        return False, user.monkeys
    user.monkeys -= amount
    return True, user.monkeys


def _credit_monkeys(repository: Repository, uid: int, amount: int) -> int:
    user = _get_or_create_user(repository, uid, "")
    if amount > 0:
        user.monkeys += amount
    return user.monkeys


async def _settle_room(repository: Repository, metrics, room: BoardRoom):
    game_id = room.game_type
    winner = room.winner

    participant_ids: dict[str, int] = {}
    for side in ("white", "black"):
        uid = room.players.get(side)
        if uid is not None:
            participant_ids[side] = uid

    for side, uid in participant_ids.items():
        name = room.player_names.get(uid, str(uid))
        labels = {"user_id": str(uid), "user_name": name, "game": game_id}
        if winner == "draw":
            metrics.inc("casino_games_total", {**labels, "result": "loss"})
        elif winner == side:
            metrics.inc("casino_games_total", {**labels, "result": "win"})
        else:
            metrics.inc("casino_games_total", {**labels, "result": "loss"})

    if room.stake > 0:
        white_uid = room.players.get("white")
        black_uid = room.players.get("black")
        pot = 0
        if white_uid is not None and white_uid in room.stake_locked:
            pot += room.stake
            metrics.inc(
                "casino_monkeys_bet_total",
                {"user_id": str(white_uid), "user_name": room.player_names.get(white_uid, str(white_uid)), "game": game_id},
                room.stake,
            )
        if black_uid is not None and black_uid in room.stake_locked:
            pot += room.stake
            metrics.inc(
                "casino_monkeys_bet_total",
                {"user_id": str(black_uid), "user_name": room.player_names.get(black_uid, str(black_uid)), "game": game_id},
                room.stake,
            )

        if winner in ALLOWED_SIDES and winner in participant_ids:
            uid = participant_ids[winner]
            _credit_monkeys(repository, uid, pot)
            metrics.inc(
                "casino_monkeys_won_total",
                {"user_id": str(uid), "user_name": room.player_names.get(uid, str(uid)), "game": game_id},
                pot,
            )
        elif winner == "draw":
            for side, uid in participant_ids.items():
                if uid in room.stake_locked:
                    _credit_monkeys(repository, uid, room.stake)
                    metrics.inc(
                        "casino_monkeys_won_total",
                        {"user_id": str(uid), "user_name": room.player_names.get(uid, str(uid)), "game": game_id},
                        room.stake,
                    )

    for bet in list(room.bets.values()):
        metrics.inc(
            "casino_monkeys_bet_total",
            {"user_id": str(bet.user_id), "user_name": bet.user_name, "game": game_id},
            bet.amount,
        )
        if winner in ALLOWED_SIDES and bet.side == winner:
            win = int(bet.amount * 1.9)
            _credit_monkeys(repository, bet.user_id, win)
            metrics.inc(
                "casino_monkeys_won_total",
                {"user_id": str(bet.user_id), "user_name": bet.user_name, "game": game_id},
                win,
            )

    await repository.save()


async def _maybe_bot_move(room: BoardRoom):
    if room.bot_side is None or room.finished or not room.started:
        return
    if room.turn != room.bot_side:
        return
    if room._bot_task and not room._bot_task.done():
        return

    async def _run():
        try:
            await asyncio.sleep(random.uniform(*BOT_MOVE_DELAY))
            if room.finished or not room.started or room.turn != room.bot_side:
                return
            if room.game_type == GAME_CHESS:
                assert room.chess_board is not None
                mv = chess_logic.choose_bot_move(room.chess_board, room.bot_difficulty)
                if mv is None:
                    room.finished = True
                    room.winner = "black" if room.turn == "white" else "white"
                    return
                room.chess_board.push(mv)
                room.last_move = {"by": room.bot_side, "move": mv.uci(), "bot": True}
                room._finalize_turn()
            else:
                assert room.checkers_board is not None
                while room.turn == room.bot_side and not room.finished:
                    mv = checkers_logic.choose_bot_move(
                        room.checkers_board,
                        room.bot_side,
                        room.checkers_forced_from,
                        room.bot_difficulty,
                    )
                    if mv is None:
                        room.finished = True
                        room.winner = "black" if room.turn == "white" else "white"
                        return
                    still_forced = room._apply_checkers_move(room.bot_side, mv, is_bot=True)
                    if not still_forced:
                        break
        except Exception:
            logger.exception("bot move failed room=%s", room.id)

    room._bot_task = asyncio.create_task(_run())
    await room._bot_task


async def _send_room_update(room: BoardRoom):
    dead_uids = await room.broadcast({"type": "room_updated", "room": room.to_dict()})
    dead_uids.update(await room.send_states())
    for uid in dead_uids:
        _remove_uid_from_room(room, uid)
        _manager.player_rooms.pop(uid, None)
        _manager.lobby_connections.pop(uid, None)
    _cleanup_dead_room_connections(room)


async def boardgames_ws_handler(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    repository: Repository = request.app["repository"]
    metrics = request.app["metrics"]
    user_id: int | None = None
    user_name: str = "Player"
    current_room: BoardRoom | None = None

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            t = data.get("type")

            if t == "auth":
                if not _is_auth_payload(data):
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid auth payload"}))
                    continue
                init_data_raw = data["initData"]
                tg_user = _validate_telegram_init_data(init_data_raw)
                if not tg_user or not tg_user.get("id"):
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid Telegram auth"}))
                    continue
                user_id = int(tg_user["id"])
                user_name = str(tg_user.get("username") or tg_user.get("first_name") or "Player")[:30]
                _manager.lobby_connections[user_id] = ws
                await ws.send_str(json.dumps({"type": "authed"}))
                await ws.send_str(json.dumps({"type": "rooms_list", "rooms": _manager.list_rooms()}, ensure_ascii=False))

            elif t == "list_rooms":
                await ws.send_str(json.dumps({"type": "rooms_list", "rooms": _manager.list_rooms()}, ensure_ascii=False))

            elif t == "create_room":
                if not user_id:
                    await ws.send_str(json.dumps({"type": "error", "message": "Not authed"}))
                    continue
                if not _is_create_room_payload(data):
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid create payload"}))
                    continue
                game_type = str(data.get("gameType", GAME_CHESS))
                if game_type not in ALLOWED_GAMES:
                    await ws.send_str(json.dumps({"type": "error", "message": "Unknown game"}))
                    continue
                stake = _safe_int(data.get("stake", 0), 0)
                if stake < 0 or stake > MAX_BET:
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid stake"}))
                    continue
                bot_enabled = bool(data.get("botEnabled", False))
                bot_side = str(data.get("botSide", "black"))
                bot_difficulty = str(data.get("botDifficulty", chess_logic.BOT_MEDIUM))
                if not bot_enabled:
                    bot_side = None
                elif bot_side not in ALLOWED_SIDES:
                    bot_side = "black"
                if bot_difficulty not in chess_logic.BOT_DIFFICULTIES:
                    bot_difficulty = chess_logic.BOT_MEDIUM

                name = str(data.get("name", "")).strip()[:50] or ("Шахматы" if game_type == GAME_CHESS else "Шашки")
                room = _manager.create_room(
                    name,
                    game_type,
                    user_id,
                    user_name,
                    stake,
                    bot_side,
                    bot_difficulty,
                )
                room.connections[user_id] = ws
                room.player_names[user_id] = user_name
                room.players["white"] = user_id
                if room.bot_side == "white":
                    room.players["white"] = None
                    room.players["black"] = user_id
                _manager.player_rooms[user_id] = room.id
                _manager.lobby_connections.pop(user_id, None)
                current_room = room
                await ws.send_str(json.dumps({"type": "room_joined", "room": room.to_dict()}, ensure_ascii=False))
                await _manager.broadcast_rooms()

            elif t == "join_room":
                if not user_id:
                    await ws.send_str(json.dumps({"type": "error", "message": "Not authed"}))
                    continue
                if user_id in _manager.player_rooms:
                    await ws.send_str(json.dumps({"type": "error", "message": "Already in room"}))
                    continue
                if not _is_join_room_payload(data):
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid join payload"}))
                    continue
                room_id = str(data.get("roomId", "")).strip()
                room = _manager.get_room(room_id)
                if not room:
                    await ws.send_str(json.dumps({"type": "error", "message": "Room not found"}))
                    continue
                requested_side = data.get("side")
                side = _resolve_join_side(room, requested_side if isinstance(requested_side, str) else None)
                room.connections[user_id] = ws
                room.player_names[user_id] = user_name
                if side in ALLOWED_SIDES:
                    room.players[side] = user_id
                else:
                    room.spectators.add(user_id)
                _manager.player_rooms[user_id] = room.id
                _manager.lobby_connections.pop(user_id, None)
                current_room = room
                await ws.send_str(json.dumps({"type": "room_joined", "room": room.to_dict(), "role": side}, ensure_ascii=False))
                await _send_room_update(room)
                await _manager.broadcast_rooms()

            elif t == "leave_room":
                if not current_room or not user_id:
                    continue
                for side in ("white", "black"):
                    if current_room.players.get(side) == user_id:
                        current_room.players[side] = None
                current_room.spectators.discard(user_id)
                current_room.connections.pop(user_id, None)
                _manager.player_rooms.pop(user_id, None)
                _manager.lobby_connections[user_id] = ws
                rid = current_room.id
                await ws.send_str(json.dumps({"type": "left_room"}))
                if not current_room.connections:
                    _manager.cleanup_room(rid)
                else:
                    await _send_room_update(current_room)
                current_room = None
                await _manager.broadcast_rooms()

            elif t == "start_game":
                if not current_room or not user_id:
                    continue
                if current_room.creator_id != user_id:
                    await ws.send_str(json.dumps({"type": "error", "message": "Only creator can start"}))
                    continue

                white_uid = current_room.players.get("white")
                black_uid = current_room.players.get("black")
                if white_uid is None and current_room.bot_side != "white":
                    await ws.send_str(json.dumps({"type": "error", "message": "Need white player"}))
                    continue
                if black_uid is None and current_room.bot_side != "black":
                    await ws.send_str(json.dumps({"type": "error", "message": "Need black player"}))
                    continue

                if current_room.stake > 0:
                    charged = []
                    for side in ("white", "black"):
                        uid = current_room.players.get(side)
                        if uid is None:
                            continue
                        ok, balance = _charge_monkeys(repository, uid, current_room.player_names.get(uid, str(uid)), current_room.stake)
                        if not ok:
                            for rollback_uid in charged:
                                _credit_monkeys(repository, rollback_uid, current_room.stake)
                            await repository.save()
                            await ws.send_str(json.dumps({"type": "error", "message": f"Not enough monkeys for stake (uid={uid}, balance={balance})"}))
                            break
                        charged.append(uid)
                        current_room.stake_locked.add(uid)
                    else:
                        await repository.save()
                        if not current_room.start_game():
                            await ws.send_str(json.dumps({"type": "error", "message": "Cannot start"}))
                            continue
                else:
                    if not current_room.start_game():
                        await ws.send_str(json.dumps({"type": "error", "message": "Cannot start"}))
                        continue

                await _send_room_update(current_room)
                await _manager.broadcast_rooms()
                await _maybe_bot_move(current_room)
                if current_room.finished:
                    await _settle_room(repository, metrics, current_room)
                await _send_room_update(current_room)

            elif t == "move":
                if not current_room or not user_id:
                    continue
                if not _is_move_payload(data):
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid move payload"}))
                    continue
                ok, reason = current_room.make_move(user_id, data)
                if not ok:
                    await ws.send_str(json.dumps({"type": "error", "message": reason}))
                    continue
                await _send_room_update(current_room)
                await _maybe_bot_move(current_room)
                if current_room.finished:
                    await _settle_room(repository, metrics, current_room)
                await _send_room_update(current_room)

            elif t == "place_bet":
                if not current_room or not user_id:
                    continue
                if not _is_bet_payload(data):
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid bet payload"}))
                    continue
                if not current_room.started or current_room.finished:
                    await ws.send_str(json.dumps({"type": "error", "message": "Betting closed"}))
                    continue
                role = current_room._viewer_role(user_id)
                if role in ALLOWED_SIDES:
                    await ws.send_str(json.dumps({"type": "error", "message": "Players cannot place spectator bets"}))
                    continue
                if user_id in current_room.bets:
                    await ws.send_str(json.dumps({"type": "error", "message": "Bet already placed"}))
                    continue
                side = str(data.get("side", ""))
                amount = _safe_int(data.get("amount", 0), 0)
                if side not in ALLOWED_SIDES:
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid side"}))
                    continue
                if amount not in ALLOWED_BETS or amount > MAX_BET:
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid amount"}))
                    continue
                ok, balance = _charge_monkeys(repository, user_id, user_name, amount)
                if not ok:
                    await ws.send_str(json.dumps({"type": "error", "message": f"Not enough monkeys ({balance})"}))
                    continue
                current_room.bets[user_id] = BoardBet(user_id, user_name, side, amount)
                await repository.save()
                await ws.send_str(json.dumps({"type": "bet_ok", "monkeys": balance}))
                await _send_room_update(current_room)

    except Exception:
        logger.exception("boardgames ws error uid=%s", user_id)
    finally:
        if user_id:
            _manager.lobby_connections.pop(user_id, None)
        if current_room and user_id:
            current_room.connections.pop(user_id, None)
            current_room.spectators.discard(user_id)
            for side in ("white", "black"):
                if current_room.players.get(side) == user_id:
                    current_room.players[side] = None
            _manager.player_rooms.pop(user_id, None)
            if current_room.connections:
                await _send_room_update(current_room)
            else:
                _manager.cleanup_room(current_room.id)
            await _manager.broadcast_rooms()
    return ws
