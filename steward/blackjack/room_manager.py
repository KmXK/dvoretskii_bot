import asyncio
import hashlib
import hmac
import json
import logging
import random
import time
import uuid
from os import environ
from urllib.parse import parse_qsl

from aiohttp import web

from steward.blackjack.engine import BlackjackGame, Player, PHASE_PLAYING, PHASE_SHOWDOWN, PHASE_WAITING, hand_value
from steward.data.models.user import User
from steward.data.repository import Repository

logger = logging.getLogger(__name__)

MONKEY_CHIP_RATE = 10
_DISCONNECT_GRACE = 60
_NEXT_ROUND_DELAY = 18
_BOT_ACTION_DELAY = (0.8, 1.6)
_BOT_ID_BASE = -2_000_000


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
        logger.exception("blackjack initData validation error")
        return None


def _find_user(repository: Repository, user_id: int) -> User | None:
    return next((u for u in repository.db.users if u.id == user_id), None)


def _get_or_create_user(repository: Repository, user_id: int, username: str = "") -> User:
    user = _find_user(repository, user_id)
    if user is None:
        user = User(user_id, username or None)
        repository.db.users.append(user)
    return user


def _normalize_start_chips(start_chips: int, play_for_monkeys: bool) -> int:
    sc = max(100, min(100000, int(start_chips)))
    if play_for_monkeys:
        sc = (sc // MONKEY_CHIP_RATE) * MONKEY_CHIP_RATE
        if sc < MONKEY_CHIP_RATE:
            sc = MONKEY_CHIP_RATE
    return sc


def _normalize_table_bet(table_bet: int) -> int:
    return max(5, min(5000, int(table_bet)))


def _charge_buy_in_monkeys(repository: Repository, user_id: int, user_name: str, chips: int) -> tuple[bool, int]:
    if chips <= 0:
        return False, 0
    buy_in_monkeys = chips // MONKEY_CHIP_RATE
    if buy_in_monkeys <= 0:
        return False, 0
    user = _get_or_create_user(repository, user_id, user_name)
    if user.monkeys < buy_in_monkeys:
        return False, buy_in_monkeys
    user.monkeys -= buy_in_monkeys
    return True, user.monkeys


def _cash_out_monkeys(repository: Repository, user_id: int, chips: int) -> int | None:
    if chips <= 0:
        return None
    monkeys = chips // MONKEY_CHIP_RATE
    if monkeys <= 0:
        return None
    user = _find_user(repository, user_id)
    if user is None:
        return None
    user.monkeys += monkeys
    return user.monkeys


def _bot_decide(state: dict, bot_index: int) -> str:
    players = state.get("players", [])
    dealer = state.get("dealer", {})
    if bot_index < 0 or bot_index >= len(players):
        return "stand"
    p = players[bot_index]
    cards = p.get("cards", [])
    total, _ = hand_value(cards)
    dealer_up = dealer.get("total", 10)

    if len(cards) == 2 and total in (10, 11) and random.random() < 0.35:
        return "double"
    if total <= 11:
        return "hit"
    if total >= 17:
        return "stand"
    if 12 <= total <= 16:
        if dealer_up >= 7:
            return "hit"
        if random.random() < 0.25:
            return "hit"
    return "stand"


class Room:
    def __init__(
        self,
        room_id: str,
        name: str,
        creator_id: int,
        start_chips: int = 1000,
        table_bet: int = 25,
        bot_count: int = 0,
        play_for_monkeys: bool = False,
    ):
        self.id = room_id
        self.name = name
        self.creator_id = creator_id
        self.connections: dict[int, web.WebSocketResponse] = {}
        self.start_chips = start_chips
        self.table_bet = table_bet
        self.bot_count = bot_count
        self.play_for_monkeys = play_for_monkeys
        self.game = BlackjackGame(start_chips=start_chips, bet_amount=table_bet)
        self.started = False
        self.ready_players: set[int] = set()
        self.chip_bank: dict[int, int] = {}
        self._bot_counter = 0
        self._next_round_task: asyncio.Task | None = None
        self._bot_task: asyncio.Task | None = None

    def _total_players(self) -> int:
        return len(self.game.players)

    def to_dict(self) -> dict:
        players = []
        for p in self.game.players:
            if p.is_bot:
                players.append({"id": p.user_id, "name": p.name, "isBot": True})
            elif p.user_id in self.connections:
                players.append({"id": p.user_id, "name": p.name})
        return {
            "id": self.id,
            "name": self.name,
            "creator_id": self.creator_id,
            "playerCount": len(players),
            "maxPlayers": 6,
            "started": self.started,
            "startChips": self.start_chips,
            "tableBet": self.table_bet,
            "botCount": self.bot_count,
            "playForMonkeys": self.play_for_monkeys,
            "monkeyChipRate": MONKEY_CHIP_RATE,
            "players": players,
        }

    def add_bots(self, count: int):
        used_names = {p.name for p in self.game.players}
        pool = ["DealerFan", "CardShark", "AceHunter", "Lucky", "Bluffless", "Shadow", "Rabbit"]
        random.shuffle(pool)
        for _ in range(count):
            self._bot_counter += 1
            bid = _BOT_ID_BASE - self._bot_counter
            name = f"🤖 {pool.pop() if pool else f'Bot {self._bot_counter}'}"
            while name in used_names:
                name = f"🤖 Bot {self._bot_counter}-{random.randint(1, 99)}"
            used_names.add(name)
            self.game.add_player(bid, name, self.start_chips, is_bot=True)

    def remove_all_bots(self):
        self.game.players = [p for p in self.game.players if not p.is_bot]

    async def broadcast(self, msg: dict):
        payload = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.connections.values()):
            try:
                await ws.send_str(payload)
            except Exception:
                pass

    async def send_states(self):
        for uid, ws in list(self.connections.items()):
            try:
                state = self.game.state_for(uid)
                state["readyPlayers"] = list(self.ready_players)
                await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))
            except Exception:
                logger.exception("blackjack send_states failed room=%s uid=%s", self.id, uid)

    async def _schedule_next_round(self):
        await asyncio.sleep(_NEXT_ROUND_DELAY)
        if not self.started:
            return
        await self.try_next_round()

    def queue_next_round(self):
        if self._next_round_task and not self._next_round_task.done():
            self._next_round_task.cancel()
        self._next_round_task = asyncio.create_task(self._schedule_next_round())

    def _mark_bots_ready(self):
        for p in self.game.players:
            if p.is_bot and not p.sitting_out and p.chips > 0:
                self.ready_players.add(p.user_id)

    def _schedule_bot_if_needed(self):
        if self.game.phase != PHASE_PLAYING:
            return
        idx = self.game.current_idx
        if idx < 0 or idx >= len(self.game.players):
            return
        p = self.game.players[idx]
        if not p.is_bot:
            return
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
        self._bot_task = asyncio.create_task(self._bot_act(idx))

    async def _bot_act(self, idx: int):
        try:
            await asyncio.sleep(random.uniform(*_BOT_ACTION_DELAY))
            if self.game.phase != PHASE_PLAYING:
                return
            if self.game.current_idx != idx:
                return
            p = self.game.players[idx]
            if not p.is_bot:
                return
            state = self.game.state_for(p.user_id)
            act = _bot_decide(state, idx)
            ok, _ = self.game.action(p.user_id, act)
            if not ok:
                self.game.action(p.user_id, "stand")
            await self.send_states()
            if self.game.phase == PHASE_SHOWDOWN:
                self.ready_players.clear()
                self._mark_bots_ready()
                self.queue_next_round()
                await self._check_all_ready()
            else:
                self._schedule_bot_if_needed()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("blackjack bot action failed room=%s idx=%s", self.id, idx)

    async def handle_ready(self, user_id: int):
        self.ready_players.add(user_id)
        await self.broadcast({
            "type": "player_ready",
            "userId": user_id,
            "readyPlayers": list(self.ready_players),
        })
        await self._check_all_ready()

    async def _check_all_ready(self):
        if self.game.phase != PHASE_SHOWDOWN:
            return
        eligible = set()
        for p in self.game.players:
            if not p.sitting_out and p.chips > 0 and (p.is_bot or p.user_id in self.connections):
                eligible.add(p.user_id)
        human_eligible = {uid for uid in eligible if uid >= 0}
        if not human_eligible or human_eligible.issubset(self.ready_players):
            if self._next_round_task and not self._next_round_task.done():
                self._next_round_task.cancel()
            await self.try_next_round()

    async def try_next_round(self):
        if not self.started or len(self.connections) == 0:
            return
        for p in self.game.players:
            if p.user_id in self.connections or p.is_bot:
                p.sitting_out = False
        seated = [p for p in self.game.players if not p.sitting_out and p.chips > 0]
        if len(seated) < 1:
            self.started = False
            self.game.phase = PHASE_WAITING
            self.remove_all_bots()
            self.game.players = [p for p in self.game.players if p.user_id in self.connections]
            await self.broadcast({"type": "game_over"})
            return
        self.ready_players.clear()
        ok = self.game.start_round()
        if not ok:
            self.started = False
            self.game.phase = PHASE_WAITING
            await self.broadcast({"type": "game_over"})
            return
        await self.send_states()
        if self.game.phase == PHASE_SHOWDOWN:
            self.ready_players.clear()
            self._mark_bots_ready()
            self.queue_next_round()
            await self._check_all_ready()
        else:
            self._schedule_bot_if_needed()

    def cancel_tasks(self):
        if self._next_round_task and not self._next_round_task.done():
            self._next_round_task.cancel()
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()

    def transfer_ownership(self):
        for uid in self.connections:
            if uid != self.creator_id:
                self.creator_id = uid
                return uid
        return None


class RoomManager:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.player_rooms: dict[int, str] = {}
        self.lobby_connections: dict[int, web.WebSocketResponse] = {}
        self._disconnect_timers: dict[int, asyncio.Task] = {}

    def list_rooms(self) -> list[dict]:
        return [r.to_dict() for r in self.rooms.values()]

    def create_room(
        self,
        name: str,
        user_id: int,
        start_chips: int = 1000,
        table_bet: int = 25,
        bot_count: int = 0,
        play_for_monkeys: bool = False,
    ) -> Room:
        room_id = uuid.uuid4().hex[:8]
        room = Room(room_id, name, user_id, start_chips, table_bet, bot_count, play_for_monkeys)
        self.rooms[room_id] = room
        return room

    def get_room(self, room_id: str) -> Room | None:
        return self.rooms.get(room_id)

    async def broadcast_rooms(self):
        payload = json.dumps({"type": "rooms_list", "rooms": self.list_rooms()}, ensure_ascii=False)
        for ws in list(self.lobby_connections.values()):
            try:
                await ws.send_str(payload)
            except Exception:
                pass

    def cleanup_room(self, room_id: str):
        room = self.rooms.get(room_id)
        if room:
            room.cancel_tasks()
            del self.rooms[room_id]

    def cancel_disconnect_timer(self, user_id: int):
        task = self._disconnect_timers.pop(user_id, None)
        if task and not task.done():
            task.cancel()


_manager = RoomManager()


async def _leave(user_id: int, room: Room, repository: Repository | None = None):
    player = next((p for p in room.game.players if p.user_id == user_id), None)
    monkeys_balance: int | None = None
    if player:
        if room.play_for_monkeys and repository is not None:
            monkeys_balance = _cash_out_monkeys(repository, user_id, player.chips)
        else:
            room.chip_bank[user_id] = player.chips

    room.connections.pop(user_id, None)
    room.ready_players.discard(user_id)
    room.game.remove_player(user_id)
    _manager.player_rooms.pop(user_id, None)

    if room.connections:
        if room.creator_id == user_id:
            room.transfer_ownership()

        if room.started:
            alive = [
                p for p in room.game.players
                if not p.sitting_out and p.chips > 0 and (p.is_bot or p.user_id in room.connections)
            ]
            humans_alive = [p for p in alive if not p.is_bot]
            if len(alive) < 1 or len(humans_alive) == 0:
                room.started = False
                room.game.phase = PHASE_WAITING
                room.remove_all_bots()
                room.game.players = [p for p in room.game.players if p.user_id in room.connections]
                await room.broadcast({"type": "game_over"})
            else:
                await room.send_states()
                room._schedule_bot_if_needed()

        await room.broadcast({"type": "room_updated", "room": room.to_dict()})
    else:
        _manager.cleanup_room(room.id)

    if room.play_for_monkeys and repository is not None:
        await repository.save()

    await _manager.broadcast_rooms()
    return monkeys_balance


async def _delayed_leave(user_id: int, room: Room, repository: Repository | None = None):
    try:
        await asyncio.sleep(_DISCONNECT_GRACE)
        _manager._disconnect_timers.pop(user_id, None)
        if _manager.player_rooms.get(user_id) == room.id and user_id not in room.connections:
            await _leave(user_id, room, repository)
    except asyncio.CancelledError:
        pass


async def blackjack_ws_handler(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    repository: Repository = request.app["repository"]
    user_id: int | None = None
    user_name: str = "Player"
    current_room: Room | None = None

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            t = data.get("type")

            if t == "auth":
                init_data_raw = str(data.get("initData", ""))
                tg_user = _validate_telegram_init_data(init_data_raw)
                if not tg_user or not tg_user.get("id"):
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid Telegram auth"}))
                    continue
                user_id = int(tg_user["id"])
                user_name = str(tg_user.get("username") or tg_user.get("first_name") or "Player")[:30]

                if user_id in _manager.player_rooms:
                    rid = _manager.player_rooms[user_id]
                    room = _manager.get_room(rid)
                    if room:
                        _manager.cancel_disconnect_timer(user_id)
                        current_room = room
                        room.connections[user_id] = ws
                        pl = next((p for p in room.game.players if p.user_id == user_id), None)
                        if pl:
                            pl.sitting_out = False
                        await ws.send_str(json.dumps({"type": "reconnected", "room": room.to_dict()}, ensure_ascii=False))
                        if room.started:
                            state = room.game.state_for(user_id)
                            state["readyPlayers"] = list(room.ready_players)
                            await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))
                        continue

                _manager.lobby_connections[user_id] = ws
                await ws.send_str(json.dumps({"type": "authed"}))

            elif t == "list_rooms":
                await ws.send_str(json.dumps({"type": "rooms_list", "rooms": _manager.list_rooms()}, ensure_ascii=False))

            elif t == "create_room":
                if not user_id:
                    await ws.send_str(json.dumps({"type": "error", "message": "Not authed"}))
                    continue
                if user_id in _manager.player_rooms:
                    await ws.send_str(json.dumps({"type": "error", "message": "Already in a room"}))
                    continue
                name = str(data.get("name", f"Room {len(_manager.rooms) + 1}"))[:40]
                play_for_monkeys = bool(data.get("playForMonkeys", False))
                sc = _normalize_start_chips(int(data.get("startChips", 1000)), play_for_monkeys)
                tb = _normalize_table_bet(int(data.get("tableBet", 25)))
                bc = max(0, min(5, int(data.get("botCount", 0))))

                monkeys_balance = None
                if play_for_monkeys:
                    ok_buy_in, payload = _charge_buy_in_monkeys(repository, user_id, user_name, sc)
                    if not ok_buy_in:
                        need = payload
                        await ws.send_str(json.dumps({"type": "error", "message": f"Need {need} monkeys to enter this room"}))
                        continue
                    monkeys_balance = payload
                    await repository.save()

                room = _manager.create_room(name, user_id, sc, tb, bc, play_for_monkeys)
                room.connections[user_id] = ws
                room.game.add_player(user_id, user_name, chips=sc)
                if bc > 0:
                    room.add_bots(bc)
                _manager.player_rooms[user_id] = room.id
                _manager.lobby_connections.pop(user_id, None)
                current_room = room
                await ws.send_str(json.dumps({
                    "type": "room_joined",
                    "room": room.to_dict(),
                    "monkeysBalance": monkeys_balance,
                }, ensure_ascii=False))
                await _manager.broadcast_rooms()

            elif t == "join_room":
                if not user_id:
                    await ws.send_str(json.dumps({"type": "error", "message": "Not authed"}))
                    continue
                if user_id in _manager.player_rooms:
                    await ws.send_str(json.dumps({"type": "error", "message": "Already in a room"}))
                    continue
                room = _manager.get_room(str(data.get("roomId", "")))
                if not room:
                    await ws.send_str(json.dumps({"type": "error", "message": "Room not found"}))
                    continue
                if room._total_players() >= 6:
                    await ws.send_str(json.dumps({"type": "error", "message": "Room full"}))
                    continue

                room.connections[user_id] = ws
                monkeys_balance = None
                if room.play_for_monkeys:
                    ok_buy_in, payload = _charge_buy_in_monkeys(repository, user_id, user_name, room.start_chips)
                    if not ok_buy_in:
                        room.connections.pop(user_id, None)
                        await ws.send_str(json.dumps({"type": "error", "message": f"Need {payload} monkeys to enter this room"}))
                        continue
                    monkeys_balance = payload
                    await repository.save()
                    chips = room.start_chips
                else:
                    saved = room.chip_bank.pop(user_id, None)
                    chips = saved if saved is not None else room.start_chips

                room.game.add_player(user_id, user_name, chips=chips)
                if room.started:
                    p = next((p for p in room.game.players if p.user_id == user_id), None)
                    if p:
                        p.sitting_out = True

                _manager.player_rooms[user_id] = room.id
                _manager.lobby_connections.pop(user_id, None)
                current_room = room
                await ws.send_str(json.dumps({
                    "type": "room_joined",
                    "room": room.to_dict(),
                    "monkeysBalance": monkeys_balance,
                }, ensure_ascii=False))
                await room.broadcast({"type": "room_updated", "room": room.to_dict()})
                await _manager.broadcast_rooms()
                if room.started:
                    state = room.game.state_for(user_id)
                    state["readyPlayers"] = list(room.ready_players)
                    await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))

            elif t == "leave_room":
                if current_room and user_id:
                    _manager.cancel_disconnect_timer(user_id)
                    monkeys_balance = await _leave(user_id, current_room, repository)
                    current_room = None
                    _manager.lobby_connections[user_id] = ws
                    await ws.send_str(json.dumps({"type": "left_room", "monkeysBalance": monkeys_balance}))

            elif t == "start_game":
                if not current_room:
                    await ws.send_str(json.dumps({"type": "error", "message": "Not in room"}))
                    continue
                if current_room.creator_id != user_id:
                    await ws.send_str(json.dumps({"type": "error", "message": "Only creator can start"}))
                    continue
                total = current_room._total_players()
                if total < 1:
                    await ws.send_str(json.dumps({"type": "error", "message": "Need at least one player"}))
                    continue

                current_room.game.players = [p for p in current_room.game.players if p.user_id in current_room.connections or p.is_bot]
                for p in current_room.game.players:
                    p.chips = current_room.start_chips
                    p.sitting_out = False
                    p.reset_round()
                current_room.game.phase = PHASE_WAITING
                current_room.started = True
                current_room.ready_players.clear()
                ok = current_room.game.start_round()
                if not ok:
                    current_room.started = False
                    await ws.send_str(json.dumps({"type": "error", "message": "Cannot start game"}))
                    continue
                await current_room.send_states()
                if current_room.game.phase == PHASE_SHOWDOWN:
                    current_room.ready_players.clear()
                    current_room._mark_bots_ready()
                    current_room.queue_next_round()
                else:
                    current_room._schedule_bot_if_needed()

            elif t == "action":
                if not current_room or not current_room.started:
                    await ws.send_str(json.dumps({"type": "error", "message": "No active game"}))
                    continue
                act = str(data.get("action", ""))
                ok, result = current_room.game.action(user_id, act)
                if not ok:
                    await ws.send_str(json.dumps({"type": "error", "message": result}))
                    continue
                await current_room.send_states()
                if current_room.game.phase == PHASE_SHOWDOWN:
                    current_room.ready_players.clear()
                    current_room._mark_bots_ready()
                    current_room.queue_next_round()
                else:
                    current_room._schedule_bot_if_needed()

            elif t == "ready":
                if not current_room or not current_room.started:
                    continue
                if current_room.game.phase != PHASE_SHOWDOWN:
                    state = current_room.game.state_for(user_id)
                    state["readyPlayers"] = list(current_room.ready_players)
                    await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))
                    continue
                await current_room.handle_ready(user_id)

            elif t == "update_settings":
                if not current_room or not user_id:
                    continue
                if current_room.creator_id != user_id:
                    await ws.send_str(json.dumps({"type": "error", "message": "Only creator can change settings"}))
                    continue
                if current_room.started:
                    await ws.send_str(json.dumps({"type": "error", "message": "Cannot change settings during game"}))
                    continue

                if "startChips" in data:
                    current_room.start_chips = _normalize_start_chips(int(data.get("startChips", current_room.start_chips)), current_room.play_for_monkeys)
                if "tableBet" in data:
                    current_room.table_bet = _normalize_table_bet(int(data.get("tableBet", current_room.table_bet)))
                    current_room.game.bet_amount = current_room.table_bet
                if "botCount" in data:
                    new_bc = max(0, min(5, int(data.get("botCount", current_room.bot_count))))
                    current_room.bot_count = new_bc
                    current_room.remove_all_bots()
                    if new_bc > 0:
                        max_bots = 6 - len(current_room.connections)
                        current_room.add_bots(min(new_bc, max_bots))
                if "playForMonkeys" in data and bool(data.get("playForMonkeys")) != current_room.play_for_monkeys:
                    await ws.send_str(json.dumps({"type": "error", "message": "Currency mode cannot be changed after room creation"}))
                    continue

                current_room.game.start_chips = current_room.start_chips
                for p in current_room.game.players:
                    p.chips = current_room.start_chips
                await current_room.broadcast({"type": "room_updated", "room": current_room.to_dict()})

    except Exception:
        logger.exception("blackjack ws error uid=%s", user_id)
    finally:
        if user_id:
            _manager.lobby_connections.pop(user_id, None)
        if current_room and user_id:
            current_room.connections.pop(user_id, None)
            pl = next((p for p in current_room.game.players if p.user_id == user_id), None)
            if current_room.started and pl:
                pl.sitting_out = True
                if current_room.game.phase == PHASE_PLAYING and current_room.game.current_idx >= 0:
                    cur = current_room.game.players[current_room.game.current_idx]
                    if cur.user_id == user_id:
                        current_room.game.action(user_id, "stand")
                        await current_room.send_states()
                        if current_room.game.phase == PHASE_SHOWDOWN:
                            current_room.ready_players.clear()
                            current_room._mark_bots_ready()
                            current_room.ready_players.add(user_id)
                            current_room.queue_next_round()
                        else:
                            current_room._schedule_bot_if_needed()
                elif current_room.game.phase == PHASE_SHOWDOWN:
                    current_room.ready_players.add(user_id)
                    await current_room._check_all_ready()
            _manager.cancel_disconnect_timer(user_id)
            _manager._disconnect_timers[user_id] = asyncio.create_task(_delayed_leave(user_id, current_room, repository))

    return ws
