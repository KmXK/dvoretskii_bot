import datetime
import logging
from datetime import timezone, timedelta

from aiohttp import web

from steward.data.models.feature_request import (
    FeatureRequest,
    FeatureRequestChange,
    FeatureRequestStatus,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.data.repository import Repository
from steward.helpers.webapp import get_webapp_deep_link
from steward.metrics.base import MetricsEngine
from steward.poker.room_manager import poker_ws_handler, _manager as poker_manager

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


def serialize_army(army):
    now = datetime.datetime.now()
    end = datetime.datetime.fromtimestamp(army.end_date)
    start = datetime.datetime.fromtimestamp(army.start_date)
    remaining = (end - now).total_seconds()
    total = (end - start).total_seconds()
    percent = max(0.0, min(1.0, 1 - remaining / total)) if total > 0 else 1.0
    return {
        "name": army.name,
        "start_date": army.start_date,
        "end_date": army.end_date,
        "remaining_seconds": max(0, remaining),
        "percent": percent,
        "done": remaining <= 0,
    }


async def handle_army(request: web.Request):
    repository: Repository = request.app["repository"]
    items = sorted(repository.db.army, key=lambda a: (a.end_date, a.start_date))
    return web.json_response([serialize_army(a) for a in items])


def serialize_todo(item):
    return {
        "id": item.id,
        "chat_id": item.chat_id,
        "text": item.text,
        "is_done": item.is_done,
    }


async def handle_todos(request: web.Request):
    repository: Repository = request.app["repository"]
    return web.json_response(
        [serialize_todo(t) for t in repository.db.todo_items]
    )


async def handle_todo_toggle(request: web.Request):
    repository: Repository = request.app["repository"]
    todo_id = int(request.match_info["id"])
    todo = next((t for t in repository.db.todo_items if t.id == todo_id), None)
    if not todo:
        return web.json_response({"error": "not found"}, status=404)
    todo.is_done = not todo.is_done
    await repository.save()
    return web.json_response(serialize_todo(todo))


def serialize_feature_request(fr):
    return {
        "id": fr.id,
        "text": fr.text,
        "author_id": fr.author_id,
        "author_name": fr.author_name,
        "status": int(fr.status),
        "creation_timestamp": fr.creation_timestamp,
        "priority": fr.priority,
        "notes": fr.notes,
        "history": [
            {
                "status": int(c.status),
                "timestamp": c.timestamp,
            }
            for c in fr.history
        ],
    }


async def handle_feature_requests(request: web.Request):
    repository: Repository = request.app["repository"]
    return web.json_response(
        [serialize_feature_request(fr) for fr in repository.db.feature_requests]
    )


async def handle_feature_request_detail(request: web.Request):
    repository: Repository = request.app["repository"]
    fr_id = int(request.match_info["id"])

    if fr_id <= 0 or fr_id > len(repository.db.feature_requests):
        return web.json_response({"error": "not found"}, status=404)

    fr = repository.db.feature_requests[fr_id - 1]
    return web.json_response(serialize_feature_request(fr))


async def handle_feature_request_update(request: web.Request):
    repository: Repository = request.app["repository"]
    fr_id = int(request.match_info["id"])

    if fr_id <= 0 or fr_id > len(repository.db.feature_requests):
        return web.json_response({"error": "not found"}, status=404)

    fr = repository.db.feature_requests[fr_id - 1]
    body = await request.json()

    if "status" in body:
        new_status = int(body["status"])
        if new_status not in [s.value for s in FeatureRequestStatus]:
            return web.json_response({"error": "invalid status"}, status=400)
        if int(fr.status) != new_status:
            fr.history.append(
                FeatureRequestChange(
                    author_id=0,
                    timestamp=datetime.datetime.now().timestamp(),
                    message_id=0,
                    status=FeatureRequestStatus(new_status),
                )
            )

    if "priority" in body:
        priority = int(body["priority"])
        if priority < 1 or priority > 5:
            return web.json_response({"error": "priority must be 1-5"}, status=400)
        fr.priority = priority

    if "note" in body:
        note = str(body["note"]).strip()
        if note:
            fr.notes.append(note)

    await repository.save()
    return web.json_response(serialize_feature_request(fr))


async def handle_feature_request_create(request: web.Request):
    repository: Repository = request.app["repository"]
    body = await request.json()

    text = str(body.get("text", "")).strip()
    if not text:
        return web.json_response({"error": "text is required"}, status=400)

    author_name = str(body.get("author_name", "Web")).strip()

    fr = FeatureRequest(
        id=len(repository.db.feature_requests) + 1,
        text=text,
        author_id=0,
        author_name=author_name,
        creation_timestamp=datetime.datetime.now().timestamp(),
        message_id=None,
        chat_id=None,
    )
    repository.db.feature_requests.append(fr)
    await repository.save()
    return web.json_response(serialize_feature_request(fr), status=201)


WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _period_range(period: str) -> str:
    now = datetime.datetime.now(MSK)
    if period == "week":
        monday = now - timedelta(days=now.weekday())
        start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return f"{max(int((now - start).total_seconds()), 60)}s"


def _user_promql(metric: str, user_id: str, range_str: str, **filters) -> str:
    filters["user_id"] = user_id
    label_filter = ", ".join(f'{k}="{v}"' for k, v in filters.items())
    return f"sum(increase({metric}{{{label_filter}}}[{range_str}]))"


def _extract_val(samples) -> int:
    return int(samples[0].value) if samples and samples[0].value else 0


async def _query_stats(metrics: MetricsEngine, user_id: str, range_str: str) -> dict:
    msgs, reacts, vids = (
        await metrics.query(_user_promql("bot_messages_total", user_id, range_str, action_type="chat")),
        await metrics.query(_user_promql("bot_messages_total", user_id, range_str, action_type="reaction")),
        await metrics.query(_user_promql("bot_downloads_total", user_id, range_str)),
    )
    return {
        "messages": _extract_val(msgs),
        "reactions": _extract_val(reacts),
        "videos": _extract_val(vids),
    }


async def handle_profile(request: web.Request):
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    user_id = request.match_info["user_id"]
    period = request.query.get("period", "day")

    rewards_map = {r.id: r for r in repository.db.rewards}
    user_rewards = [
        {
            "id": r.id,
            "name": r.name,
            "emoji": r.emoji,
            "description": r.description,
            "custom_emoji_id": r.custom_emoji_id,
        }
        for ur in repository.db.user_rewards
        if ur.user_id == int(user_id)
        and (r := rewards_map.get(ur.reward_id)) is not None
    ]

    stats = await _query_stats(metrics, user_id, _period_range(period))

    return web.json_response({
        "rewards": user_rewards,
        "stats": stats,
    })


async def handle_profile_history(request: web.Request):
    metrics: MetricsEngine = request.app["metrics"]
    user_id = request.match_info["user_id"]
    period = request.query.get("period", "day")

    now = datetime.datetime.now(MSK)
    days_count = 30 if period == "month" else 7
    history = []

    for days_ago in range(days_count - 1, -1, -1):
        day = now - timedelta(days=days_ago)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        if days_ago == 0:
            range_str = f"{max(int((now - day_start).total_seconds()), 60)}s"
            offset_str = ""
        else:
            range_str = "86400s"
            offset_str = f"{days_ago * 86400}s"

        def build(metric, offset, r=range_str, **flt):
            flt["user_id"] = user_id
            lf = ", ".join(f'{k}="{v}"' for k, v in flt.items())
            off = f" offset {offset}" if offset else ""
            return f"sum(increase({metric}{{{lf}}}[{r}]{off}))"

        msgs = await metrics.query(build("bot_messages_total", offset_str, action_type="chat"))
        reacts = await metrics.query(build("bot_messages_total", offset_str, action_type="reaction"))
        vids = await metrics.query(build("bot_downloads_total", offset_str))

        label = day_start.strftime("%d.%m") if period == "month" else WEEKDAYS[day_start.weekday()]

        history.append({
            "label": label,
            "messages": _extract_val(msgs),
            "reactions": _extract_val(reacts),
            "videos": _extract_val(vids),
        })

    return web.json_response(history)


async def handle_poker_stats(request: web.Request):
    metrics: MetricsEngine = request.app["metrics"]
    user_id = request.match_info["user_id"]

    try:
        def pq(metric, **flt):
            flt["user_id"] = user_id
            lf = ", ".join(f'{k}="{v}"' for k, v in flt.items())
            return f"sum({metric}{{{lf}}})"

        hands_s = await metrics.query(pq("poker_hands_total"))
        hands_won_s = await metrics.query(pq("poker_hands_total", result="win"))
        hands_fold_s = await metrics.query(pq("poker_hands_total", result="fold"))
        hands_lost_s = await metrics.query(pq("poker_hands_total", result="loss"))
        games_s = await metrics.query(pq("poker_games_total"))
        games_won_s = await metrics.query(pq("poker_games_won_total"))
        chips_won_s = await metrics.query(pq("poker_chips_won_total"))
        chips_lost_s = await metrics.query(pq("poker_chips_lost_total"))

        combo_names = [
            "High Card", "Pair", "Two Pair", "Three of a Kind",
            "Straight", "Flush", "Full House", "Four of a Kind", "Straight Flush",
        ]
        combos = []
        for cn in combo_names:
            collected_s = await metrics.query(pq("poker_combinations_total", combination=cn))
            won_s = await metrics.query(pq("poker_combinations_won_total", combination=cn))
            collected = _extract_val(collected_s)
            won = _extract_val(won_s)
            if collected > 0:
                combos.append({"name": cn, "collected": collected, "won": won})

        combos.sort(key=lambda x: x["collected"], reverse=True)

        return web.json_response({
            "hands": _extract_val(hands_s),
            "handsWon": _extract_val(hands_won_s),
            "handsFolded": _extract_val(hands_fold_s),
            "handsLost": _extract_val(hands_lost_s),
            "games": _extract_val(games_s),
            "gamesWon": _extract_val(games_won_s),
            "chipsWon": _extract_val(chips_won_s),
            "chipsLost": _extract_val(chips_lost_s),
            "combos": combos,
        })
    except Exception:
        return web.json_response({
            "hands": 0, "handsWon": 0, "handsFolded": 0, "handsLost": 0,
            "games": 0, "gamesWon": 0, "chipsWon": 0, "chipsLost": 0, "combos": [],
        })


async def handle_user_chats(request: web.Request):
    repository: Repository = request.app["repository"]
    user_id = int(request.match_info["user_id"])

    user = next((u for u in repository.db.users if u.id == user_id), None)
    if not user:
        return web.json_response({"chats": []})

    chat_ids = getattr(user, 'chat_ids', []) or []
    chats_map = {c.id: c for c in repository.db.chats}
    result = []
    for cid in chat_ids:
        chat = chats_map.get(cid)
        if chat:
            result.append({"id": chat.id, "name": chat.name})

    return web.json_response({"chats": result})


_invitation_messages: dict[str, dict[int, int]] = {}


async def handle_poker_invite(request: web.Request):
    bot = request.app.get("bot")
    if not bot:
        return web.json_response({"error": "Bot not available"}, status=503)

    body = await request.json()
    chat_ids = body.get("chatIds", [])
    room_name = str(body.get("roomName", "Poker Room"))
    room_id = str(body.get("roomId", ""))
    player_count = int(body.get("playerCount", 1))
    max_players = int(body.get("maxPlayers", 8))
    creator_name = str(body.get("creatorName", "Someone"))

    if not chat_ids or not room_id:
        return web.json_response({"error": "chatIds and roomId required"}, status=400)

    app_link = get_webapp_deep_link(bot)

    text = (
        f"🃏 <b>Poker — {room_name}</b>\n\n"
        f"👤 {creator_name} invites you to play!\n"
        f"👥 Players: {player_count}/{max_players}"
    )

    reply_markup = None
    if app_link:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Join Game", url=app_link)]
        ])

    sent = {}
    for cid in chat_ids:
        try:
            msg = await bot.send_message(chat_id=cid, text=text, parse_mode="HTML", reply_markup=reply_markup)
            sent[cid] = msg.message_id
        except Exception:
            logger.warning(f"Failed to send poker invite to chat {cid}")

    if room_id not in _invitation_messages:
        _invitation_messages[room_id] = {}
    _invitation_messages[room_id].update(sent)
    return web.json_response({"sent": len(sent)})


async def handle_poker_invite_update(request: web.Request):
    bot = request.app.get("bot")
    if not bot:
        return web.json_response({"error": "Bot not available"}, status=503)

    body = await request.json()
    room_id = str(body.get("roomId", ""))
    room_name = str(body.get("roomName", "Poker Room"))
    player_count = int(body.get("playerCount", 1))
    max_players = int(body.get("maxPlayers", 8))

    msgs = _invitation_messages.get(room_id, {})
    if not msgs:
        return web.json_response({"updated": 0})

    app_link = get_webapp_deep_link(bot)

    text = (
        f"🃏 <b>Poker — {room_name}</b>\n\n"
        f"👥 Players: {player_count}/{max_players}\n"
        f"{'🟢 Seats available!' if player_count < max_players else '🔴 Room full'}"
    )

    reply_markup = None
    if app_link:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Join Game", url=app_link)]
        ])

    updated = 0
    for cid, mid in list(msgs.items()):
        try:
            await bot.edit_message_text(chat_id=cid, message_id=mid, text=text, parse_mode="HTML", reply_markup=reply_markup)
            updated += 1
        except Exception:
            pass

    return web.json_response({"updated": updated})


CASINO_GAME_IDS = {"slots", "coinflip", "roulette", "slots5x5"}
CASINO_INITIAL_BALANCE = 100
CASINO_DAILY_BONUS = 50
CASINO_BONUS_COOLDOWN = 86400


def _find_user(repository: Repository, uid: int):
    return next((u for u in repository.db.users if u.id == uid), None)


def _get_or_create_user(repository: Repository, uid: int, username: str = ""):
    user = _find_user(repository, uid)
    if user is None:
        from steward.data.models.user import User
        user = User(uid, username or None)
        repository.db.users.append(user)
    return user


async def handle_casino_balance(request: web.Request):
    repository: Repository = request.app["repository"]
    uid = int(request.match_info["user_id"])
    user = _find_user(repository, uid)
    if not user:
        return web.json_response({"monkeys": CASINO_INITIAL_BALANCE, "lastBonusClaim": 0})
    return web.json_response({
        "monkeys": user.monkeys,
        "lastBonusClaim": user.casino_last_bonus,
    })


async def handle_casino_event(request: web.Request):
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    try:
        body = await request.json()
        user_id = str(body["userId"])
        user_name = str(body.get("userName", ""))
        game = str(body["game"])
        bet = int(body.get("bet", 0))
        win = int(body.get("win", 0))
        if game not in CASINO_GAME_IDS:
            return web.json_response({"error": "unknown game"}, status=400)

        user = _get_or_create_user(repository, int(user_id), user_name)
        delta = win - bet
        user.monkeys = max(0, user.monkeys + delta)
        await repository.save()

        labels = {"user_id": user_id, "user_name": user_name, "game": game}
        result = "win" if win > 0 else "loss"
        metrics.inc("casino_games_total", {**labels, "result": result})
        if bet > 0:
            metrics.inc("casino_monkeys_bet_total", labels, bet)
        if win > 0:
            metrics.inc("casino_monkeys_won_total", labels, win)
        return web.json_response({"ok": True, "monkeys": user.monkeys})
    except Exception:
        logger.exception("casino event error")
        return web.json_response({"error": "bad request"}, status=400)


async def handle_casino_bonus(request: web.Request):
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    try:
        body = await request.json()
        user_id = str(body["userId"])
        user_name = str(body.get("userName", ""))

        user = _get_or_create_user(repository, int(user_id), user_name)
        import time as _time
        now = _time.time()
        if user.casino_last_bonus and now - user.casino_last_bonus < CASINO_BONUS_COOLDOWN:
            return web.json_response({"error": "cooldown", "monkeys": user.monkeys}, status=429)

        user.monkeys += CASINO_DAILY_BONUS
        user.casino_last_bonus = now
        await repository.save()

        metrics.inc("casino_bonus_total", {"user_id": user_id, "user_name": user_name}, CASINO_DAILY_BONUS)
        return web.json_response({"ok": True, "monkeys": user.monkeys, "lastBonusClaim": user.casino_last_bonus})
    except Exception:
        logger.exception("casino bonus error")
        return web.json_response({"error": "bad request"}, status=400)


async def handle_casino_stats(request: web.Request):
    metrics: MetricsEngine = request.app["metrics"]
    user_id = request.match_info["user_id"]

    try:
        def pq(metric, **flt):
            flt["user_id"] = user_id
            lf = ", ".join(f'{k}="{v}"' for k, v in flt.items())
            return f"sum({metric}{{{lf}}})"

        games_won_s = await metrics.query(pq("casino_games_total", result="win"))
        games_lost_s = await metrics.query(pq("casino_games_total", result="loss"))
        won_s = await metrics.query(pq("casino_monkeys_won_total"))
        bet_s = await metrics.query(pq("casino_monkeys_bet_total"))
        bonus_s = await metrics.query(pq("casino_bonus_total"))

        per_game = []
        for gid in sorted(CASINO_GAME_IDS):
            gw = _extract_val(await metrics.query(pq("casino_games_total", game=gid, result="win")))
            gl = _extract_val(await metrics.query(pq("casino_games_total", game=gid, result="loss")))
            gmon = _extract_val(await metrics.query(pq("casino_monkeys_won_total", game=gid)))
            gbet = _extract_val(await metrics.query(pq("casino_monkeys_bet_total", game=gid)))
            if gw + gl > 0:
                per_game.append({"game": gid, "gamesWon": gw, "gamesLost": gl, "won": gmon, "bet": gbet})

        return web.json_response({
            "gamesWon": _extract_val(games_won_s),
            "gamesLost": _extract_val(games_lost_s),
            "won": _extract_val(won_s),
            "bet": _extract_val(bet_s),
            "bonus": _extract_val(bonus_s),
            "games": per_game,
        })
    except Exception:
        logger.exception("casino stats error")
        return web.json_response({
            "gamesWon": 0, "gamesLost": 0, "won": 0, "bet": 0, "bonus": 0, "games": [],
        })


async def handle_poker_invite_delete(request: web.Request):
    bot = request.app.get("bot")
    if not bot:
        return web.json_response({"error": "Bot not available"}, status=503)

    body = await request.json()
    room_id = str(body.get("roomId", ""))

    msgs = _invitation_messages.pop(room_id, {})
    deleted = 0
    for cid, mid in msgs.items():
        try:
            await bot.delete_message(chat_id=cid, message_id=mid)
            deleted += 1
        except Exception:
            pass

    return web.json_response({"deleted": deleted})


async def start_api_server(repository: Repository, metrics: MetricsEngine, port: int = 8080, bot=None):
    app = web.Application()
    app["repository"] = repository
    app["metrics"] = metrics
    app["bot"] = bot

    if bot:
        async def _on_room_cleanup(room_id):
            msgs = _invitation_messages.pop(room_id, {})
            for cid, mid in msgs.items():
                try:
                    await bot.delete_message(chat_id=cid, message_id=mid)
                except Exception:
                    pass
        poker_manager._on_room_cleanup = _on_room_cleanup
    app.router.add_get("/api/army", handle_army)
    app.router.add_get("/api/todos", handle_todos)
    app.router.add_patch("/api/todos/{id}", handle_todo_toggle)
    app.router.add_get("/api/feature-requests", handle_feature_requests)
    app.router.add_post("/api/feature-requests", handle_feature_request_create)
    app.router.add_get("/api/feature-requests/{id}", handle_feature_request_detail)
    app.router.add_patch("/api/feature-requests/{id}", handle_feature_request_update)
    app.router.add_get("/api/profile/{user_id}", handle_profile)
    app.router.add_get("/api/profile/{user_id}/history", handle_profile_history)
    app.router.add_get("/api/poker/stats/{user_id}", handle_poker_stats)
    app.router.add_get("/api/casino/balance/{user_id}", handle_casino_balance)
    app.router.add_post("/api/casino/event", handle_casino_event)
    app.router.add_post("/api/casino/bonus", handle_casino_bonus)
    app.router.add_get("/api/casino/stats/{user_id}", handle_casino_stats)
    app.router.add_get("/api/user/{user_id}/chats", handle_user_chats)
    app.router.add_post("/api/poker/invite", handle_poker_invite)
    app.router.add_post("/api/poker/invite/update", handle_poker_invite_update)
    app.router.add_post("/api/poker/invite/delete", handle_poker_invite_delete)
    app.router.add_get("/ws/poker", poker_ws_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"API server started on port {port}")
