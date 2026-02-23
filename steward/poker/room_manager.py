import asyncio
import json
import uuid
import random
import logging

from aiohttp import web

from steward.poker.engine import PokerGame, Player, PHASE_SHOWDOWN, PHASE_WAITING
from steward.poker.bot_ai import decide, BOT_NAMES, DIFFICULTIES, DIFFICULTY_MEDIUM

logger = logging.getLogger(__name__)

_NEXT_HAND_DELAY = 30
_BOT_ACTION_DELAY = (0.8, 2.0)
_BOT_ID_BASE = -1_000_000
_DISCONNECT_GRACE = 60


class Room:
    def __init__(self, room_id: str, name: str, creator_id: int,
                 small_blind: int = 10, big_blind: int = 20, start_chips: int = 1000,
                 bot_count: int = 0, bot_difficulty: str = DIFFICULTY_MEDIUM):
        self.id = room_id
        self.name = name
        self.creator_id = creator_id
        self.connections: dict[int, web.WebSocketResponse] = {}
        self.game = PokerGame(small_blind, big_blind, start_chips)
        self.started = False
        self._next_hand_task: asyncio.Task | None = None
        self._bot_task: asyncio.Task | None = None
        self.ready_players: set[int] = set()
        self.chip_bank: dict[int, int] = {}
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.start_chips = start_chips
        self.bot_count = bot_count
        self.bot_difficulty = bot_difficulty
        self._bot_counter = 0
        self._last_metrics_hand = 0
        self._metrics = None

    def _human_count(self):
        return len([p for p in self.game.players if not p.is_bot])

    def _total_players(self):
        return len(self.game.players)

    def to_dict(self):
        human_players = [
            {"id": p.user_id, "name": p.name}
            for p in self.game.players
            if not p.is_bot and p.user_id in self.connections
        ]
        bot_players = [
            {"id": p.user_id, "name": p.name, "isBot": True}
            for p in self.game.players
            if p.is_bot
        ]
        return {
            "id": self.id,
            "name": self.name,
            "creator_id": self.creator_id,
            "playerCount": len(self.connections) + len(bot_players),
            "humanCount": len(self.connections),
            "maxPlayers": 8,
            "started": self.started,
            "smallBlind": self.small_blind,
            "bigBlind": self.big_blind,
            "startChips": self.start_chips,
            "botCount": self.bot_count,
            "botDifficulty": self.bot_difficulty,
            "players": human_players + bot_players,
        }

    def add_bots(self, count: int):
        used_names = {p.name for p in self.game.players}
        available = [n for n in BOT_NAMES if n not in used_names]
        random.shuffle(available)

        for i in range(count):
            self._bot_counter += 1
            bot_id = _BOT_ID_BASE - self._bot_counter
            if available:
                bot_name = available.pop()
            else:
                bot_name = f"Bot {self._bot_counter}"
            p = Player(bot_id, f"🤖 {bot_name}", self.start_chips, is_bot=True)
            self.game.players.append(p)

    def remove_all_bots(self):
        self.game.players = [p for p in self.game.players if not p.is_bot]

    async def broadcast(self, msg: dict):
        data = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.connections.values()):
            try:
                await ws.send_str(data)
            except Exception:
                pass

    async def send_states(self):
        for uid, ws in list(self.connections.items()):
            try:
                state = self.game.state_for(uid)
                state["readyPlayers"] = list(self.ready_players)
                await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))
            except Exception:
                logger.exception("send_states error for uid=%s room=%s", uid, self.id)

    async def _schedule_next(self):
        await asyncio.sleep(_NEXT_HAND_DELAY)
        if not self.started:
            return
        logger.info("room=%s auto-starting next hand after %ds", self.id, _NEXT_HAND_DELAY)
        await self._try_next_hand()

    async def _try_next_hand(self):
        humans_connected = len(self.connections)
        if not self.started or humans_connected == 0:
            logger.info(
                "room=%s _try_next_hand skipped: started=%s connections=%d",
                self.id, self.started, humans_connected,
            )
            return

        for p in self.game.players:
            if p.user_id in self.connections:
                p.sitting_out = False
            if p.is_bot:
                p.sitting_out = False

        seated = [p for p in self.game.players if not p.sitting_out and p.chips > 0]
        logger.info("room=%s _try_next_hand: seated=%d", self.id, len(seated))

        if len(seated) >= 2:
            self.ready_players.clear()
            ok = self.game.start_hand()
            if not ok:
                logger.warning("room=%s start_hand() returned False despite seated=%d", self.id, len(seated))
                self.game.phase = PHASE_SHOWDOWN
                await self.send_states()
                self.queue_next_hand()
                return
            logger.info(
                "room=%s hand #%d started, phase=%s, players=%d",
                self.id, self.game.hand_num, self.game.phase,
                len([p for p in self.game.players if not p.folded and not p.sitting_out]),
            )
            await self.send_states()
            if self.game.phase == PHASE_SHOWDOWN:
                self.ready_players.clear()
                self._mark_bots_ready()
                self.queue_next_hand()
            else:
                self._schedule_bot_if_needed()
        else:
            logger.info("room=%s game over, not enough players with chips", self.id)
            if self._metrics:
                self.emit_game_over(self._metrics)
            self.started = False
            self.game.phase = PHASE_WAITING
            self.remove_all_bots()
            self.game.players = [
                p for p in self.game.players
                if p.user_id in self.connections
            ]
            await self.broadcast({"type": "game_over"})

    def queue_next_hand(self):
        if self._next_hand_task and not self._next_hand_task.done():
            self._next_hand_task.cancel()
        self._next_hand_task = asyncio.create_task(self._schedule_next())

    def cancel_tasks(self):
        if self._next_hand_task and not self._next_hand_task.done():
            self._next_hand_task.cancel()
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()

    def transfer_ownership(self):
        for uid in self.connections:
            if uid != self.creator_id:
                self.creator_id = uid
                return uid
        return None

    def _mark_bots_ready(self):
        for p in self.game.players:
            if p.is_bot and not p.sitting_out and p.chips > 0:
                self.ready_players.add(p.user_id)

    def _schedule_bot_if_needed(self):
        if self.game.phase in (PHASE_WAITING, PHASE_SHOWDOWN):
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

    async def _bot_act(self, player_idx: int):
        try:
            delay = random.uniform(*_BOT_ACTION_DELAY)
            await asyncio.sleep(delay)

            if self.game.phase in (PHASE_WAITING, PHASE_SHOWDOWN):
                return
            if self.game.current_idx != player_idx:
                return

            p = self.game.players[player_idx]
            if not p.is_bot:
                return

            act, amount = decide(self.game, player_idx, self.bot_difficulty)
            ok, result = self.game.action(p.user_id, act, amount)

            if not ok:
                logger.warning(
                    "room=%s bot uid=%s action=%s failed: %s, folding",
                    self.id, p.user_id, act, result,
                )
                ok, result = self.game.action(p.user_id, "fold")
                if not ok:
                    ok, result = self.game.action(p.user_id, "check")

            logger.info(
                "room=%s bot uid=%s(%s) action=%s amount=%s phase=%s",
                self.id, p.user_id, p.name, act, amount, self.game.phase,
            )

            await self.send_states()

            if self.game.phase == PHASE_SHOWDOWN:
                self.ready_players.clear()
                self._mark_bots_ready()
                self.queue_next_hand()
                await self._check_all_ready()
            else:
                self._schedule_bot_if_needed()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("room=%s _bot_act error idx=%s", self.id, player_idx)

    async def _check_all_ready(self):
        if self.game.phase != PHASE_SHOWDOWN:
            return
        eligible = set()
        for p in self.game.players:
            if not p.sitting_out and p.chips > 0:
                if p.is_bot or p.user_id in self.connections:
                    eligible.add(p.user_id)
        human_eligible = {uid for uid in eligible if uid >= 0}

        if not human_eligible or human_eligible.issubset(self.ready_players):
            if self._next_hand_task and not self._next_hand_task.done():
                self._next_hand_task.cancel()
            if self._metrics:
                try:
                    self._emit_hand_metrics(self._metrics)
                except Exception:
                    logger.exception("room=%s _emit_hand_metrics failed in _check_all_ready", self.id)
            await self._try_next_hand()

    async def handle_ready(self, user_id: int, metrics=None):
        self.ready_players.add(user_id)
        await self.broadcast({
            "type": "player_ready",
            "userId": user_id,
            "readyPlayers": list(self.ready_players),
        })

        if self.game.phase != PHASE_SHOWDOWN:
            logger.debug("room=%s ready from uid=%s ignored: phase=%s", self.id, user_id, self.game.phase)
            return

        eligible = set()
        for p in self.game.players:
            if not p.sitting_out and p.chips > 0:
                if p.is_bot or p.user_id in self.connections:
                    eligible.add(p.user_id)
        human_eligible = {uid for uid in eligible if uid >= 0}

        logger.info(
            "room=%s handle_ready uid=%s: human_eligible=%s ready=%s",
            self.id, user_id, human_eligible, self.ready_players,
        )

        if not human_eligible or human_eligible.issubset(self.ready_players):
            if self._next_hand_task and not self._next_hand_task.done():
                self._next_hand_task.cancel()

            if metrics:
                try:
                    self._emit_hand_metrics(metrics)
                except Exception:
                    logger.exception("room=%s _emit_hand_metrics failed", self.id)

            await self._try_next_hand()

    def _emit_hand_metrics(self, metrics):
        if self.game.hand_num <= self._last_metrics_hand:
            return
        self._last_metrics_hand = self.game.hand_num
        results = self.game.results
        if not results:
            return
        winners = set(results.get("winners", []))
        hands = results.get("hands", {})

        for p in self.game.players:
            if p.sitting_out or p.is_bot:
                continue
            labels = {"user_id": str(p.user_id), "user_name": p.name}
            i = next((j for j, pl in enumerate(self.game.players) if pl.user_id == p.user_id), -1)

            if p.folded and i not in winners:
                result = "fold"
            elif i in winners:
                result = "win"
            else:
                result = "loss"

            metrics.inc("poker_hands_total", {**labels, "result": result})

            if result == "win":
                won = hands.get(i, {}).get("won", 0)
                if won:
                    metrics.inc("poker_chips_won_total", labels, won)
                    net = won - p.total_bet
                    if net < 0:
                        metrics.inc("poker_chips_lost_total", labels, -net)
            elif p.total_bet > 0:
                metrics.inc("poker_chips_lost_total", labels, p.total_bet)

            if i in hands:
                combo_name = hands[i].get("name", "")
                if combo_name:
                    metrics.inc("poker_combinations_total", {**labels, "combination": combo_name})
                    if i in winners:
                        metrics.inc("poker_combinations_won_total", {**labels, "combination": combo_name})

    def emit_game_start(self, metrics):
        for p in self.game.players:
            if not p.sitting_out and not p.is_bot:
                metrics.inc("poker_games_total", {"user_id": str(p.user_id), "user_name": p.name})

    def emit_game_over(self, metrics):
        best = None
        for p in self.game.players:
            if not p.sitting_out and not p.is_bot and (best is None or p.chips > best.chips):
                best = p
        if best and best.chips > 0:
            metrics.inc("poker_games_won_total", {"user_id": str(best.user_id), "user_name": best.name})


class RoomManager:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.player_rooms: dict[int, str] = {}
        self.lobby_connections: dict[int, web.WebSocketResponse] = {}
        self._on_room_cleanup: callable = None
        self._disconnect_timers: dict[int, asyncio.Task] = {}

    def cancel_disconnect_timer(self, user_id: int):
        task = self._disconnect_timers.pop(user_id, None)
        if task and not task.done():
            task.cancel()

    def list_rooms(self):
        return [r.to_dict() for r in self.rooms.values()]

    async def broadcast_rooms(self):
        data = json.dumps({"type": "rooms_list", "rooms": self.list_rooms()}, ensure_ascii=False)
        for ws in list(self.lobby_connections.values()):
            try:
                await ws.send_str(data)
            except Exception:
                pass

    def create_room(self, name: str, user_id: int, user_name: str,
                    small_blind: int = 10, big_blind: int = 20, start_chips: int = 1000,
                    bot_count: int = 0, bot_difficulty: str = DIFFICULTY_MEDIUM) -> Room:
        room_id = uuid.uuid4().hex[:8]
        room = Room(room_id, name, user_id, small_blind, big_blind, start_chips, bot_count, bot_difficulty)
        self.rooms[room_id] = room
        return room

    def get_room(self, room_id: str) -> Room | None:
        return self.rooms.get(room_id)

    def cleanup_room(self, room_id: str):
        room = self.rooms.get(room_id)
        if room:
            room.cancel_tasks()
            del self.rooms[room_id]
        if self._on_room_cleanup:
            asyncio.ensure_future(self._on_room_cleanup(room_id))


_manager = RoomManager()


async def _leave(user_id: int, room: Room, metrics=None):
    player = next((p for p in room.game.players if p.user_id == user_id), None)
    if player:
        room.chip_bank[user_id] = player.chips

    room.connections.pop(user_id, None)
    room.ready_players.discard(user_id)
    room.game.remove_player(user_id)
    _manager.player_rooms.pop(user_id, None)

    logger.info("room=%s uid=%s left, connections=%d", room.id, user_id, len(room.connections))

    if room.connections:
        if room.creator_id == user_id:
            room.transfer_ownership()

        if room.started:
            active_with_chips = [
                p for p in room.game.players
                if not p.sitting_out and p.chips > 0 and (p.is_bot or p.user_id in room.connections)
            ]
            humans_with_chips = [p for p in active_with_chips if not p.is_bot]

            if len(active_with_chips) < 2 or len(humans_with_chips) == 0:
                logger.info("room=%s not enough players after leave, ending game", room.id)
                if room.game.phase == PHASE_SHOWDOWN and metrics:
                    try:
                        room._emit_hand_metrics(metrics)
                    except Exception:
                        logger.exception("room=%s _emit_hand_metrics failed in _leave", room.id)
                if metrics:
                    room.emit_game_over(metrics)
                room.started = False
                room.game.phase = PHASE_WAITING
                room.remove_all_bots()
                room.game.players = [
                    p for p in room.game.players
                    if p.user_id in room.connections
                ]
                await room.broadcast({"type": "game_over"})
            else:
                if room.game.phase == PHASE_SHOWDOWN:
                    await room._check_all_ready()
                    if room.game.phase != PHASE_SHOWDOWN:
                        pass
                    else:
                        await room.send_states()
                else:
                    await room.send_states()
                    room._schedule_bot_if_needed()

        await room.broadcast({"type": "room_updated", "room": room.to_dict()})
    else:
        logger.info("room=%s no connections left, cleaning up", room.id)
        _manager.cleanup_room(room.id)

    await _manager.broadcast_rooms()


async def _delayed_leave(user_id: int, room: Room, metrics=None):
    try:
        await asyncio.sleep(_DISCONNECT_GRACE)
        _manager._disconnect_timers.pop(user_id, None)
        if _manager.player_rooms.get(user_id) == room.id and user_id not in room.connections:
            logger.info("uid=%s disconnect grace expired, leaving room=%s", user_id, room.id)
            await _leave(user_id, room, metrics)
    except asyncio.CancelledError:
        pass


async def poker_ws_handler(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    metrics = request.app.get("metrics")
    user_id: int | None = None
    user_name: str = "Player"
    current_room: Room | None = None

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                t = data.get("type")

                if t == "auth":
                    user_id = data.get("userId")
                    user_name = str(data.get("name", "Player"))[:30]
                    if not user_id:
                        await ws.send_str(json.dumps({"type": "error", "message": "userId required"}))
                        continue

                    if user_id in _manager.player_rooms:
                        rid = _manager.player_rooms[user_id]
                        room = _manager.get_room(rid)
                        if room:
                            _manager.cancel_disconnect_timer(user_id)
                            current_room = room
                            room.connections[user_id] = ws
                            player = next((p for p in room.game.players if p.user_id == user_id), None)
                            if player:
                                player.sitting_out = False
                            logger.info("uid=%s reconnected to room=%s", user_id, rid)
                            await ws.send_str(json.dumps({"type": "reconnected", "room": room.to_dict()}, ensure_ascii=False))
                            if room.started:
                                state = room.game.state_for(user_id)
                                state["readyPlayers"] = list(room.ready_players)
                                await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))
                                if room.game.phase == PHASE_SHOWDOWN:
                                    room.queue_next_hand()
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
                    sb = max(1, min(1000, int(data.get("smallBlind", 10))))
                    bb = max(sb * 2, min(2000, int(data.get("bigBlind", sb * 2))))
                    sc = max(bb * 10, min(100000, int(data.get("startChips", 1000))))
                    bc = max(0, min(7, int(data.get("botCount", 0))))
                    bd = str(data.get("botDifficulty", DIFFICULTY_MEDIUM))
                    if bd not in DIFFICULTIES:
                        bd = DIFFICULTY_MEDIUM

                    room = _manager.create_room(name, user_id, user_name, sb, bb, sc, bc, bd)
                    room.connections[user_id] = ws
                    room.game.add_player(user_id, user_name)
                    if bc > 0:
                        room.add_bots(bc)
                    _manager.player_rooms[user_id] = room.id
                    _manager.lobby_connections.pop(user_id, None)
                    current_room = room
                    logger.info("uid=%s created room=%s with %d bots", user_id, room.id, bc)
                    await ws.send_str(json.dumps({"type": "room_joined", "room": room.to_dict()}, ensure_ascii=False))
                    await _manager.broadcast_rooms()

                elif t == "join_room":
                    if not user_id:
                        await ws.send_str(json.dumps({"type": "error", "message": "Not authed"}))
                        continue
                    if user_id in _manager.player_rooms:
                        await ws.send_str(json.dumps({"type": "error", "message": "Already in a room"}))
                        continue

                    room_id = data.get("roomId")
                    room = _manager.get_room(room_id)
                    if not room:
                        await ws.send_str(json.dumps({"type": "error", "message": "Room not found"}))
                        continue
                    if room._total_players() >= 8:
                        await ws.send_str(json.dumps({"type": "error", "message": "Room full"}))
                        continue

                    room.connections[user_id] = ws
                    saved_chips = room.chip_bank.pop(user_id, None)
                    chips = saved_chips if saved_chips is not None else room.start_chips

                    if room.started:
                        room.game.add_player(user_id, user_name, chips)
                        p = next((p for p in room.game.players if p.user_id == user_id), None)
                        if p:
                            p.sitting_out = True
                            p.folded = True
                    else:
                        room.game.add_player(user_id, user_name, chips)

                    _manager.player_rooms[user_id] = room.id
                    _manager.lobby_connections.pop(user_id, None)
                    current_room = room
                    logger.info("uid=%s joined room=%s", user_id, room.id)
                    await ws.send_str(json.dumps({"type": "room_joined", "room": room.to_dict()}, ensure_ascii=False))
                    await room.broadcast({"type": "room_updated", "room": room.to_dict()})
                    await _manager.broadcast_rooms()

                    if room.started:
                        state = room.game.state_for(user_id)
                        state["readyPlayers"] = list(room.ready_players)
                        await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))

                elif t == "leave_room":
                    if current_room and user_id:
                        _manager.cancel_disconnect_timer(user_id)
                        await _leave(user_id, current_room, metrics)
                        current_room = None
                        _manager.lobby_connections[user_id] = ws
                        await ws.send_str(json.dumps({"type": "left_room"}))

                elif t == "start_game":
                    if not current_room:
                        await ws.send_str(json.dumps({"type": "error", "message": "Not in room"}))
                        continue
                    if current_room.creator_id != user_id:
                        await ws.send_str(json.dumps({"type": "error", "message": "Only creator can start"}))
                        continue

                    total = current_room._total_players()
                    if total < 2:
                        await ws.send_str(json.dumps({"type": "error", "message": "Need 2+ players (including bots)"}))
                        continue

                    current_room.game.players = [
                        p for p in current_room.game.players
                        if p.user_id in current_room.connections or p.is_bot
                    ]
                    for p in current_room.game.players:
                        p.chips = current_room.start_chips
                        p.reset_hand()
                        p.sitting_out = False
                    current_room.game.phase = PHASE_WAITING
                    current_room.game.results = None
                    current_room.game.last_action = None
                    current_room.game.hand_num = 0
                    current_room.game.dealer_idx = -1

                    current_room.started = True
                    current_room.ready_players.clear()
                    current_room._metrics = metrics
                    ok = current_room.game.start_hand()
                    if not ok:
                        current_room.started = False
                        await ws.send_str(json.dumps({"type": "error", "message": "Cannot start game"}))
                        continue
                    logger.info("room=%s game started by uid=%s, hand #%d", current_room.id, user_id, current_room.game.hand_num)
                    if metrics:
                        current_room.emit_game_start(metrics)
                    await current_room.send_states()

                    if current_room.game.phase == PHASE_SHOWDOWN:
                        current_room.ready_players.clear()
                        current_room._mark_bots_ready()
                        current_room.queue_next_hand()
                    else:
                        current_room._schedule_bot_if_needed()

                elif t == "action":
                    if not current_room or not current_room.started:
                        await ws.send_str(json.dumps({"type": "error", "message": "No active game"}))
                        continue

                    try:
                        act = data.get("action")
                        amount = int(data.get("amount", 0))
                        ok, result = current_room.game.action(user_id, act, amount)
                        if not ok:
                            await ws.send_str(json.dumps({"type": "error", "message": result}))
                            continue

                        logger.info(
                            "room=%s uid=%s action=%s amount=%s phase=%s",
                            current_room.id, user_id, act, amount, current_room.game.phase,
                        )
                        await current_room.send_states()

                        if current_room.game.phase == PHASE_SHOWDOWN:
                            current_room.ready_players.clear()
                            current_room._mark_bots_ready()
                            current_room.queue_next_hand()
                        else:
                            current_room._schedule_bot_if_needed()
                    except Exception:
                        logger.exception("room=%s action error uid=%s act=%s", current_room.id, user_id, data.get("action"))
                        await ws.send_str(json.dumps({"type": "error", "message": "Internal error"}))

                elif t == "ready":
                    if not current_room or not current_room.started:
                        continue
                    if current_room.game.phase != PHASE_SHOWDOWN:
                        try:
                            state = current_room.game.state_for(user_id)
                            state["readyPlayers"] = list(current_room.ready_players)
                            await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))
                        except Exception:
                            logger.exception("room=%s state sync failed for uid=%s", current_room.id, user_id)
                        continue
                    try:
                        await current_room.handle_ready(user_id, metrics)
                    except Exception:
                        logger.exception("room=%s handle_ready error uid=%s", current_room.id, user_id)

                elif t == "update_settings":
                    if not current_room or not user_id:
                        continue
                    if current_room.creator_id != user_id:
                        await ws.send_str(json.dumps({"type": "error", "message": "Only creator can change settings"}))
                        continue
                    if current_room.started:
                        await ws.send_str(json.dumps({"type": "error", "message": "Cannot change settings during game"}))
                        continue

                    sb = data.get("smallBlind")
                    bb = data.get("bigBlind")
                    sc = data.get("startChips")
                    bc = data.get("botCount")
                    bd = data.get("botDifficulty")

                    if sb is not None:
                        current_room.small_blind = max(1, min(1000, int(sb)))
                    if bb is not None:
                        current_room.big_blind = max(current_room.small_blind * 2, min(2000, int(bb)))
                    if sc is not None:
                        current_room.start_chips = max(current_room.big_blind * 10, min(100000, int(sc)))
                    if bd is not None and str(bd) in DIFFICULTIES:
                        current_room.bot_difficulty = str(bd)

                    if bc is not None:
                        new_bc = max(0, min(7, int(bc)))
                        old_bc = current_room.bot_count
                        current_room.bot_count = new_bc
                        current_room.remove_all_bots()
                        if new_bc > 0:
                            max_bots = 8 - len(current_room.connections)
                            current_room.add_bots(min(new_bc, max_bots))

                    current_room.game.small_blind = current_room.small_blind
                    current_room.game.big_blind = current_room.big_blind
                    current_room.game.start_chips = current_room.start_chips

                    for p in current_room.game.players:
                        p.chips = current_room.start_chips

                    await current_room.broadcast({"type": "room_updated", "room": current_room.to_dict()})

            elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                break
    except Exception:
        logger.exception("poker ws error uid=%s", user_id)
    finally:
        if user_id:
            _manager.lobby_connections.pop(user_id, None)
        if current_room and user_id:
            current_room.connections.pop(user_id, None)

            if current_room.started:
                player = next((p for p in current_room.game.players if p.user_id == user_id), None)
                if player:
                    player.sitting_out = True

                    idx = current_room.game.current_idx
                    if (0 <= idx < len(current_room.game.players)
                            and current_room.game.players[idx].user_id == user_id
                            and current_room.game.phase not in (PHASE_WAITING, PHASE_SHOWDOWN)):
                        try:
                            current_room.game.action(user_id, "fold")
                            await current_room.send_states()
                            if current_room.game.phase == PHASE_SHOWDOWN:
                                current_room.ready_players.clear()
                                current_room._mark_bots_ready()
                                current_room.ready_players.add(user_id)
                                current_room.queue_next_hand()
                            else:
                                current_room._schedule_bot_if_needed()
                        except Exception:
                            logger.exception("room=%s auto-fold failed uid=%s", current_room.id, user_id)
                    elif current_room.game.phase == PHASE_SHOWDOWN:
                        current_room.ready_players.add(user_id)
                        await current_room._check_all_ready()

                try:
                    await current_room.broadcast({"type": "room_updated", "room": current_room.to_dict()})
                except Exception:
                    pass

            _manager.cancel_disconnect_timer(user_id)
            _manager._disconnect_timers[user_id] = asyncio.create_task(
                _delayed_leave(user_id, current_room, metrics)
            )
            logger.info("uid=%s disconnected from room=%s, grace=%ds", user_id, current_room.id, _DISCONNECT_GRACE)

    return ws
