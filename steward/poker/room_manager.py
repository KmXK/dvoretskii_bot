import asyncio
import json
import uuid
import logging

from aiohttp import web

from steward.poker.engine import PokerGame, PHASE_SHOWDOWN, PHASE_WAITING

logger = logging.getLogger(__name__)


class Room:
    def __init__(self, room_id: str, name: str, creator_id: int,
                 small_blind: int = 10, big_blind: int = 20, start_chips: int = 1000):
        self.id = room_id
        self.name = name
        self.creator_id = creator_id
        self.connections: dict[int, web.WebSocketResponse] = {}
        self.game = PokerGame(small_blind, big_blind, start_chips)
        self.started = False
        self._next_hand_task: asyncio.Task | None = None
        self.ready_players: set[int] = set()
        self.chip_bank: dict[int, int] = {}
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.start_chips = start_chips
        self._last_metrics_hand = 0
        self._metrics = None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "creator_id": self.creator_id,
            "playerCount": len(self.connections),
            "maxPlayers": 8,
            "started": self.started,
            "smallBlind": self.small_blind,
            "bigBlind": self.big_blind,
            "startChips": self.start_chips,
            "players": [
                {"id": p.user_id, "name": p.name}
                for p in self.game.players
                if p.user_id in self.connections
            ],
        }

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
                pass

    async def _schedule_next(self):
        await asyncio.sleep(120)
        if not self.started:
            return
        await self._try_next_hand()

    async def _try_next_hand(self):
        if not self.started or len(self.connections) < 2:
            return

        for p in self.game.players:
            if p.user_id in self.connections:
                p.sitting_out = False

        seated = [p for p in self.game.players if not p.sitting_out and p.chips > 0]
        if len(seated) >= 2:
            self.ready_players.clear()
            self.game.start_hand()
            await self.send_states()
        else:
            if self._metrics:
                self.emit_game_over(self._metrics)
            self.started = False
            self.game.phase = PHASE_WAITING
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

    def transfer_ownership(self):
        for uid in self.connections:
            if uid != self.creator_id:
                self.creator_id = uid
                return uid
        return None

    async def handle_ready(self, user_id: int, metrics=None):
        self.ready_players.add(user_id)
        await self.broadcast({
            "type": "player_ready",
            "userId": user_id,
            "readyPlayers": list(self.ready_players),
        })

        eligible = set()
        for p in self.game.players:
            if p.user_id in self.connections and not p.sitting_out and p.chips > 0:
                eligible.add(p.user_id)

        if not eligible or eligible.issubset(self.ready_players):
            if self._next_hand_task and not self._next_hand_task.done():
                self._next_hand_task.cancel()

            if metrics:
                self._emit_hand_metrics(metrics)

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
            if p.sitting_out:
                continue
            labels = {"user_id": str(p.user_id), "user_name": p.name}
            i = next((j for j, pl in enumerate(self.game.players) if pl.user_id == p.user_id), -1)

            metrics.inc("poker_hands_total", labels)

            if p.folded and i not in winners:
                metrics.inc("poker_hands_total", {**labels, "result": "fold"})
                if p.total_bet > 0:
                    metrics.inc("poker_chips_lost_total", labels, p.total_bet)
            elif i in winners:
                metrics.inc("poker_hands_total", {**labels, "result": "win"})
                won = hands.get(i, {}).get("won", 0)
                if won:
                    metrics.inc("poker_chips_won_total", labels, won)
                    net = won - p.total_bet
                    if net < 0:
                        metrics.inc("poker_chips_lost_total", labels, -net)
            else:
                metrics.inc("poker_hands_total", {**labels, "result": "loss"})
                if p.total_bet > 0:
                    metrics.inc("poker_chips_lost_total", labels, p.total_bet)

            if i in hands:
                combo_name = hands[i].get("name", "")
                if combo_name:
                    metrics.inc("poker_combinations_total", {**labels, "combination": combo_name})
                    if i in winners:
                        metrics.inc("poker_combinations_won_total", {**labels, "combination": combo_name})

    def emit_game_start(self, metrics):
        for p in self.game.players:
            if not p.sitting_out:
                metrics.inc("poker_games_total", {"user_id": str(p.user_id), "user_name": p.name})

    def emit_game_over(self, metrics):
        best = None
        for p in self.game.players:
            if not p.sitting_out and (best is None or p.chips > best.chips):
                best = p
        if best and best.chips > 0:
            metrics.inc("poker_games_won_total", {"user_id": str(best.user_id), "user_name": best.name})


class RoomManager:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.player_rooms: dict[int, str] = {}
        self.lobby_connections: dict[int, web.WebSocketResponse] = {}
        self._on_room_cleanup: callable = None

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
                    small_blind: int = 10, big_blind: int = 20, start_chips: int = 1000) -> Room:
        room_id = uuid.uuid4().hex[:8]
        room = Room(room_id, name, user_id, small_blind, big_blind, start_chips)
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

    if room.connections:
        if room.creator_id == user_id:
            room.transfer_ownership()

        if room.started:
            active_with_chips = [p for p in room.game.players if not p.sitting_out and p.chips > 0]
            if len(active_with_chips) < 2:
                if room.game.phase == PHASE_SHOWDOWN and metrics:
                    room._emit_hand_metrics(metrics)
                if metrics:
                    room.emit_game_over(metrics)
                room.started = False
                room.game.phase = PHASE_WAITING
                room.game.players = [
                    p for p in room.game.players
                    if p.user_id in room.connections
                ]
                await room.broadcast({"type": "game_over"})
            else:
                if room.game.phase == PHASE_SHOWDOWN:
                    eligible = set()
                    for p in room.game.players:
                        if p.user_id in room.connections and not p.sitting_out and p.chips > 0:
                            eligible.add(p.user_id)
                    if eligible and eligible.issubset(room.ready_players):
                        if room._next_hand_task and not room._next_hand_task.done():
                            room._next_hand_task.cancel()
                        if metrics:
                            room._emit_hand_metrics(metrics)
                        await room._try_next_hand()
                    else:
                        await room.send_states()
                else:
                    await room.send_states()

        await room.broadcast({"type": "room_updated", "room": room.to_dict()})
    else:
        _manager.cleanup_room(room.id)

    await _manager.broadcast_rooms()


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
                            current_room = room
                            room.connections[user_id] = ws
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
                    sb = max(1, min(1000, int(data.get("smallBlind", 10))))
                    bb = max(sb * 2, min(2000, int(data.get("bigBlind", sb * 2))))
                    sc = max(bb * 10, min(100000, int(data.get("startChips", 1000))))

                    room = _manager.create_room(name, user_id, user_name, sb, bb, sc)
                    room.connections[user_id] = ws
                    room.game.add_player(user_id, user_name)
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
                        await ws.send_str(json.dumps({"type": "error", "message": "Already in a room"}))
                        continue

                    room_id = data.get("roomId")
                    room = _manager.get_room(room_id)
                    if not room:
                        await ws.send_str(json.dumps({"type": "error", "message": "Room not found"}))
                        continue
                    if len(room.connections) >= 8:
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
                    await ws.send_str(json.dumps({"type": "room_joined", "room": room.to_dict()}, ensure_ascii=False))
                    await room.broadcast({"type": "room_updated", "room": room.to_dict()})
                    await _manager.broadcast_rooms()

                    if room.started:
                        state = room.game.state_for(user_id)
                        state["readyPlayers"] = list(room.ready_players)
                        await ws.send_str(json.dumps({"type": "game_state", "state": state}, ensure_ascii=False))

                elif t == "leave_room":
                    if current_room and user_id:
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
                    if len(current_room.connections) < 2:
                        await ws.send_str(json.dumps({"type": "error", "message": "Need 2+ players"}))
                        continue

                    current_room.game.players = [
                        p for p in current_room.game.players
                        if p.user_id in current_room.connections
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
                    if metrics:
                        current_room.emit_game_start(metrics)
                    await current_room.send_states()

                elif t == "action":
                    if not current_room or not current_room.started:
                        await ws.send_str(json.dumps({"type": "error", "message": "No active game"}))
                        continue

                    act = data.get("action")
                    amount = int(data.get("amount", 0))
                    ok, result = current_room.game.action(user_id, act, amount)
                    if not ok:
                        await ws.send_str(json.dumps({"type": "error", "message": result}))
                        continue

                    await current_room.send_states()

                    if current_room.game.phase == PHASE_SHOWDOWN:
                        current_room.ready_players.clear()
                        current_room.queue_next_hand()

                elif t == "ready":
                    if not current_room or not current_room.started:
                        continue
                    if current_room.game.phase != PHASE_SHOWDOWN:
                        continue
                    await current_room.handle_ready(user_id, metrics)

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

                    if sb is not None:
                        current_room.small_blind = max(1, min(1000, int(sb)))
                    if bb is not None:
                        current_room.big_blind = max(current_room.small_blind * 2, min(2000, int(bb)))
                    if sc is not None:
                        current_room.start_chips = max(current_room.big_blind * 10, min(100000, int(sc)))

                    current_room.game.small_blind = current_room.small_blind
                    current_room.game.big_blind = current_room.big_blind
                    current_room.game.start_chips = current_room.start_chips

                    for p in current_room.game.players:
                        p.chips = current_room.start_chips

                    await current_room.broadcast({"type": "room_updated", "room": current_room.to_dict()})

            elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                break
    except Exception:
        logger.exception("poker ws error")
    finally:
        if user_id:
            _manager.lobby_connections.pop(user_id, None)
        if current_room and user_id:
            await _leave(user_id, current_room, metrics)

    return ws
