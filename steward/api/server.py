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
from steward.blackjack.room_manager import blackjack_ws_handler
from steward.boardgames.room_manager import boardgames_ws_handler

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


def _casino_achievements(total_games: int, total_wins: int, chess_games: int, checkers_games: int) -> list[dict]:
    achievements = []
    if total_games >= 5:
        achievements.append({"id": "first_steps", "title": "Первые шаги", "description": "Сыграть 5 матчей"})
    if total_games >= 25:
        achievements.append({"id": "veteran", "title": "Ветеран", "description": "Сыграть 25 матчей"})
    if total_wins >= 10:
        achievements.append({"id": "winner10", "title": "Победитель", "description": "Одержать 10 побед"})
    if total_wins >= 50:
        achievements.append({"id": "winner50", "title": "Легенда", "description": "Одержать 50 побед"})
    if chess_games >= 10:
        achievements.append({"id": "chess_master", "title": "Шахматист", "description": "Сыграть 10 партий в шахматы"})
    if checkers_games >= 10:
        achievements.append({"id": "checkers_master", "title": "Шашист", "description": "Сыграть 10 партий в шашки"})
    return achievements


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
    users_map = {u.id: u for u in repository.db.users}

    def _reward_holder_name(reward) -> str | None:
        if not reward.dynamic_key:
            return None
        ur = next((x for x in repository.db.user_rewards if x.reward_id == reward.id), None)
        if ur is None:
            return None
        holder = users_map.get(ur.user_id)
        return f"@{holder.username}" if holder and holder.username else str(ur.user_id)

    user_rewards = [
        {
            "id": r.id,
            "name": r.name,
            "emoji": r.emoji,
            "description": r.description,
            "custom_emoji_id": r.custom_emoji_id,
            "dynamic_key": r.dynamic_key,
            "holder": _reward_holder_name(r),
        }
        for ur in repository.db.user_rewards
        if ur.user_id == int(user_id)
        and (r := rewards_map.get(ur.reward_id)) is not None
    ]

    stats = await _query_stats(metrics, user_id, _period_range(period))
    profile_user = users_map.get(int(user_id))
    stand = None
    if (
        profile_user is not None
        and profile_user.stand_name
        and profile_user.stand_description
    ):
        stand = {
            "name": profile_user.stand_name,
            "description": profile_user.stand_description,
        }

    return web.json_response({
        "rewards": user_rewards,
        "stats": stats,
        "stand": stand,
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
            return f"sum(increase({metric}{{{lf}}}[365d]))"

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
_boardgame_invitation_messages: dict[str, dict[int, int]] = {}


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


import hashlib
import hmac
import json as _json
import secrets
import time as _time
import uuid
import re
from os import environ
from urllib.parse import parse_qsl

from aiohttp import ClientSession

from steward.delayed_action.reminder import ReminderDelayedAction, ReminderGenerator, CompletedReminder
from steward.data.models.birthday import Birthday
from steward.features.timezone import (
    _CITY_TIMEZONES as CITY_TIMEZONES,
    _OFFSET_RE as OFFSET_RE,
    _time_by_offset,
    _time_by_city,
)

CASINO_GAME_IDS = {"slots", "coinflip", "roulette", "slots5x5", "rocket"}
_CASINO_STATS_GAME_IDS = CASINO_GAME_IDS | {"race", "chess", "checkers"}
CASINO_INITIAL_BALANCE = 100
CASINO_DAILY_BONUS = 50
CASINO_BONUS_COOLDOWN = 86400
CASINO_MAX_BET = {"slots": 10, "coinflip": 50, "roulette": 50, "slots5x5": 10, "rocket": 50}
CASINO_MAX_WIN = {"slots": 1500, "coinflip": 95, "roulette": 1800, "slots5x5": 5000, "rocket": 5000}
CASINO_SESSION_TTL = 86400
CASINO_SPIN_COOLDOWN = 1.5

_casino_sessions: dict[str, dict] = {}
_casino_last_spin: dict[str, float] = {}


def _validate_telegram_init_data(init_data_raw: str) -> dict | None:
    bot_token = environ.get("TELEGRAM_BOT_TOKEN", "")
    if not init_data_raw or not bot_token:
        return None
    try:
        params = dict(parse_qsl(init_data_raw, keep_blank_values=True))
        received_hash = params.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(params.items())
        )
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        user_str = params.get("user")
        if user_str:
            return _json.loads(user_str)
        return None
    except Exception:
        logger.exception("initData validation error")
        return None


def _casino_session_from_cookie(request: web.Request) -> dict | None:
    sid = request.cookies.get("casino_sid")
    if not sid:
        return None
    sess = _casino_sessions.get(sid)
    if not sess:
        return None
    if _time.time() - sess["ts"] > CASINO_SESSION_TTL:
        _casino_sessions.pop(sid, None)
        return None
    return sess


def _find_user(repository: Repository, uid: int):
    return next((u for u in repository.db.users if u.id == uid), None)


def _get_or_create_user(repository: Repository, uid: int, username: str = ""):
    user = _find_user(repository, uid)
    if user is None:
        from steward.data.models.user import User
        user = User(uid, username or None)
        repository.db.users.append(user)
    return user


async def handle_casino_session(request: web.Request):
    try:
        body = await request.json()
        init_data_raw = str(body.get("initData", ""))

        tg_user = _validate_telegram_init_data(init_data_raw)
        if not tg_user:
            return web.json_response({"error": "invalid initData"}, status=403)

        user_id = str(tg_user["id"])
        user_name = tg_user.get("username", "") or tg_user.get("first_name", "")

        old_sid = request.cookies.get("casino_sid")
        if old_sid:
            _casino_sessions.pop(old_sid, None)

        sid = secrets.token_urlsafe(48)
        token = secrets.token_urlsafe(32)
        _casino_sessions[sid] = {"user_id": user_id, "user_name": user_name, "token": token, "ts": _time.time()}

        repository: Repository = request.app["repository"]
        user = _find_user(repository, int(user_id))
        data = {
            "monkeys": user.monkeys if user else CASINO_INITIAL_BALANCE,
            "lastBonusClaim": user.casino_last_bonus if user else 0,
            "token": token,
        }
        resp = web.json_response(data)
        resp.set_cookie(
            "casino_sid", sid,
            max_age=CASINO_SESSION_TTL,
            httponly=True,
            secure=True,
            samesite="Lax",
            path="/api/casino",
        )
        return resp
    except Exception:
        logger.exception("casino session error")
        return web.json_response({"error": "bad request"}, status=400)


async def handle_casino_balance(request: web.Request):
    sess = _casino_session_from_cookie(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    repository: Repository = request.app["repository"]
    uid = int(sess["user_id"])
    user = _find_user(repository, uid)
    if not user:
        return web.json_response({"monkeys": CASINO_INITIAL_BALANCE, "lastBonusClaim": 0})
    return web.json_response({
        "monkeys": user.monkeys,
        "lastBonusClaim": user.casino_last_bonus,
    })


async def handle_casino_event(request: web.Request):
    sess = _casino_session_from_cookie(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    try:
        body = await request.json()
        user_id = sess["user_id"]
        user_name = sess["user_name"]
        game = str(body["game"])
        bet = int(body.get("bet", 0))
        win = int(body.get("win", 0))
        token = str(body.get("token", ""))

        if game not in CASINO_GAME_IDS:
            return web.json_response({"error": "unknown game"}, status=400)

        if token != sess.get("token", ""):
            return web.json_response({"error": "invalid token"}, status=403)

        now = _time.time()
        last = _casino_last_spin.get(user_id, 0)
        if now - last < CASINO_SPIN_COOLDOWN:
            return web.json_response({"error": "too fast"}, status=429)

        max_bet = CASINO_MAX_BET.get(game, 50)
        max_win = CASINO_MAX_WIN.get(game, 100)
        if bet < 0 or win < 0 or bet > max_bet or win > max_win:
            return web.json_response({"error": "invalid bet/win"}, status=400)

        user = _get_or_create_user(repository, int(user_id), user_name)
        if bet > user.monkeys:
            return web.json_response({"error": "insufficient balance"}, status=400)
        delta = win - bet
        user.monkeys = max(0, user.monkeys + delta)
        _casino_last_spin[user_id] = now
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
    sess = _casino_session_from_cookie(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    try:
        user_id = sess["user_id"]
        user_name = sess["user_name"]

        user = _get_or_create_user(repository, int(user_id), user_name)
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
    sess = _casino_session_from_cookie(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    metrics: MetricsEngine = request.app["metrics"]
    user_id = sess["user_id"]

    try:
        def pq(metric, **flt):
            flt["user_id"] = user_id
            lf = ", ".join(f'{k}="{v}"' for k, v in flt.items())
            return f"sum(increase({metric}{{{lf}}}[365d]))"

        games_won_s = await metrics.query(pq("casino_games_total", result="win"))
        games_lost_s = await metrics.query(pq("casino_games_total", result="loss"))
        won_s = await metrics.query(pq("casino_monkeys_won_total"))
        bet_s = await metrics.query(pq("casino_monkeys_bet_total"))
        bonus_s = await metrics.query(pq("casino_bonus_total"))

        per_game = []
        for gid in sorted(_CASINO_STATS_GAME_IDS):
            gw = _extract_val(await metrics.query(pq("casino_games_total", game=gid, result="win")))
            gl = _extract_val(await metrics.query(pq("casino_games_total", game=gid, result="loss")))
            gmon = _extract_val(await metrics.query(pq("casino_monkeys_won_total", game=gid)))
            gbet = _extract_val(await metrics.query(pq("casino_monkeys_bet_total", game=gid)))
            if gw + gl > 0:
                per_game.append({"game": gid, "gamesWon": gw, "gamesLost": gl, "won": gmon, "bet": gbet})

        chess_games = next((g for g in per_game if g["game"] == "chess"), None)
        checkers_games = next((g for g in per_game if g["game"] == "checkers"), None)
        chess_total = (chess_games["gamesWon"] + chess_games["gamesLost"]) if chess_games else 0
        checkers_total = (checkers_games["gamesWon"] + checkers_games["gamesLost"]) if checkers_games else 0
        total_wins = _extract_val(games_won_s)
        total_losses = _extract_val(games_lost_s)
        total_games = total_wins + total_losses

        return web.json_response({
            "gamesWon": total_wins,
            "gamesLost": total_losses,
            "won": _extract_val(won_s),
            "bet": _extract_val(bet_s),
            "bonus": _extract_val(bonus_s),
            "games": per_game,
            "boardgames": {
                "matches": chess_total + checkers_total,
                "wins": (chess_games["gamesWon"] if chess_games else 0) + (checkers_games["gamesWon"] if checkers_games else 0),
                "chessMatches": chess_total,
                "chessWins": chess_games["gamesWon"] if chess_games else 0,
                "checkersMatches": checkers_total,
                "checkersWins": checkers_games["gamesWon"] if checkers_games else 0,
            },
            "achievements": _casino_achievements(
                total_games,
                total_wins,
                chess_total,
                checkers_total,
            ),
        })
    except Exception:
        logger.exception("casino stats error")
        return web.json_response({
            "gamesWon": 0, "gamesLost": 0, "won": 0, "bet": 0, "bonus": 0, "games": [],
            "boardgames": {
                "matches": 0,
                "wins": 0,
                "chessMatches": 0,
                "chessWins": 0,
                "checkersMatches": 0,
                "checkersWins": 0,
            },
            "achievements": [],
        })


ROCKET_SEED_TTL = 14400


def _get_rocket_seed():
    period = int(_time.time() / ROCKET_SEED_TTL)
    bot_token = environ.get("TELEGRAM_BOT_TOKEN", "default")
    return hashlib.sha256(f"rocket:{bot_token}:{period}".encode()).hexdigest()


async def handle_rocket_init(request: web.Request):
    sess = _casino_session_from_cookie(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    repository: Repository = request.app["repository"]
    uid = int(sess["user_id"])
    user = _find_user(repository, uid)
    return web.json_response({
        "seed": _get_rocket_seed(),
        "serverTime": _time.time() * 1000,
        "monkeys": user.monkeys if user else CASINO_INITIAL_BALANCE,
    })


RACE_SEED_TTL = 14400
RACE_CYCLE = 15
RACE_BET_PHASE = 7
RACE_RUN_PHASE = 5
RACE_MAX_BET = 50

RACE_MONKEYS = [
    {"name": "Бананчик", "emoji": "🍌", "weight": 30, "mult": 2.8},
    {"name": "Кокос", "emoji": "🥥", "weight": 25, "mult": 3.4},
    {"name": "Шимпа", "emoji": "🐒", "weight": 20, "mult": 4.2},
    {"name": "Горилла", "emoji": "🦍", "weight": 13, "mult": 6.5},
    {"name": "Мандарин", "emoji": "🍊", "weight": 8, "mult": 10.0},
    {"name": "Кинг-Конг", "emoji": "👑", "weight": 4, "mult": 20.0},
]
RACE_TOTAL_WEIGHT = sum(m["weight"] for m in RACE_MONKEYS)

_race_bets: dict[tuple[int, int], list[dict]] = {}
_race_settled: set[tuple[int, int]] = set()


def _imul(a: int, b: int) -> int:
    return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF


def _cyrb53(s: str, seed: int = 0) -> int:
    h1 = (0xDEADBEEF ^ seed) & 0xFFFFFFFF
    h2 = (0x41C6CE57 ^ seed) & 0xFFFFFFFF
    for ch in s:
        c = ord(ch)
        h1 = _imul(h1 ^ c, 2654435761)
        h2 = _imul(h2 ^ c, 1597334677)
    h1 = _imul(h1 ^ (h1 >> 16), 2246822507)
    h1 = (h1 ^ _imul(h2 ^ (h2 >> 16), 3266489909)) & 0xFFFFFFFF
    h2 = _imul(h2 ^ (h2 >> 16), 2246822507)
    h2 = (h2 ^ _imul(h1 ^ (h1 >> 16), 3266489909)) & 0xFFFFFFFF
    return (2097151 & h2) * 4294967296 + h1


def _get_race_seed(period: int) -> str:
    bot_token = environ.get("TELEGRAM_BOT_TOKEN", "default")
    return hashlib.sha256(f"race:{bot_token}:{period}".encode()).hexdigest()


def _race_info(now_s: float):
    period = int(now_s / RACE_SEED_TTL)
    period_start = period * RACE_SEED_TTL
    seed = _get_race_seed(period)
    elapsed = now_s - period_start
    round_num = int(elapsed / RACE_CYCLE)
    offset = elapsed - round_num * RACE_CYCLE
    if offset < RACE_BET_PHASE:
        phase = "betting"
    elif offset < RACE_BET_PHASE + RACE_RUN_PHASE:
        phase = "racing"
    else:
        phase = "result"
    return period, seed, round_num, phase, offset


def _race_winner(seed: str, round_num: int) -> int:
    h = _cyrb53(f"{seed}:{round_num}:race")
    r = h % RACE_TOTAL_WEIGHT
    for i, m in enumerate(RACE_MONKEYS):
        r -= m["weight"]
        if r < 0:
            return i
    return 0


def _settle_past_races(repository: Repository, metrics: MetricsEngine) -> bool:
    now_s = _time.time()
    cur_period, _, cur_round, _, _ = _race_info(now_s)
    cur_key = (cur_period, cur_round)
    changed = False
    for key in list(_race_bets.keys()):
        if key == cur_key or key in _race_settled:
            continue
        bet_period, bet_round = key
        round_end = bet_period * RACE_SEED_TTL + (bet_round + 1) * RACE_CYCLE
        if now_s < round_end:
            continue
        _race_settled.add(key)
        bets = _race_bets.pop(key, [])
        if not bets:
            continue
        bet_seed = _get_race_seed(bet_period)
        winner_idx = _race_winner(bet_seed, bet_round)
        mult = RACE_MONKEYS[winner_idx]["mult"]
        for be in bets:
            uid = int(be["user_id"])
            user = _find_user(repository, uid)
            if not user:
                continue
            labels = {"user_id": be["user_id"], "user_name": be["user_name"], "game": "race"}
            metrics.inc("casino_monkeys_bet_total", labels, be["amount"])
            if be["monkey_idx"] == winner_idx:
                win = int(be["amount"] * mult)
                user.monkeys += win
                metrics.inc("casino_games_total", {**labels, "result": "win"})
                metrics.inc("casino_monkeys_won_total", labels, win)
            else:
                metrics.inc("casino_games_total", {**labels, "result": "loss"})
        changed = True
    if len(_race_settled) > 300:
        to_remove = sorted(_race_settled)[:len(_race_settled) - 100]
        for r in to_remove:
            _race_settled.discard(r)
    return changed


async def handle_race_init(request: web.Request):
    sess = _casino_session_from_cookie(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    uid = int(sess["user_id"])
    if _settle_past_races(repository, metrics):
        await repository.save()
    user = _find_user(repository, uid)
    now_s = _time.time()
    _, seed, _, _, _ = _race_info(now_s)
    return web.json_response({
        "seed": seed,
        "serverTime": now_s * 1000,
        "monkeys": user.monkeys if user else CASINO_INITIAL_BALANCE,
    })


async def handle_race_bet(request: web.Request):
    sess = _casino_session_from_cookie(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    try:
        body = await request.json()
        user_id = sess["user_id"]
        user_name = sess["user_name"]
        monkey_idx = int(body.get("monkeyIdx", -1))
        amount = int(body.get("amount", 0))
        if monkey_idx < 0 or monkey_idx >= len(RACE_MONKEYS):
            return web.json_response({"error": "invalid monkey"}, status=400)
        if amount not in (5, 10, 25, 50):
            return web.json_response({"error": "invalid amount"}, status=400)
        now_s = _time.time()
        period, _, round_num, phase, _ = _race_info(now_s)
        if phase != "betting":
            return web.json_response({"error": "betting closed"}, status=400)
        _settle_past_races(repository, metrics)
        key = (period, round_num)
        round_bets = _race_bets.get(key, [])
        if any(b["user_id"] == user_id for b in round_bets):
            return web.json_response({"error": "already bet"}, status=400)
        user = _get_or_create_user(repository, int(user_id), user_name)
        if amount > user.monkeys:
            return web.json_response({"error": "insufficient balance"}, status=400)
        user.monkeys -= amount
        bet_entry = {
            "user_id": user_id,
            "user_name": user_name,
            "monkey_idx": monkey_idx,
            "amount": amount,
        }
        if key not in _race_bets:
            _race_bets[key] = []
        _race_bets[key].append(bet_entry)
        await repository.save()
        return web.json_response({
            "ok": True,
            "monkeys": user.monkeys,
            "bets": _race_bets.get(key, []),
            "round": round_num,
        })
    except Exception:
        logger.exception("race bet error")
        return web.json_response({"error": "bad request"}, status=400)


async def handle_race_bets(request: web.Request):
    sess = _casino_session_from_cookie(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    uid = int(sess["user_id"])
    if _settle_past_races(repository, metrics):
        await repository.save()
    now_s = _time.time()
    period, _, round_num, phase, offset = _race_info(now_s)
    key = (period, round_num)
    bets = _race_bets.get(key, [])
    user = _find_user(repository, uid)
    return web.json_response({
        "round": round_num,
        "phase": phase,
        "offset": offset * 1000,
        "bets": bets,
        "monkeys": user.monkeys if user else CASINO_INITIAL_BALANCE,
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


async def handle_boardgame_invite(request: web.Request):
    bot = request.app.get("bot")
    if not bot:
        return web.json_response({"error": "Bot not available"}, status=503)

    body = await request.json()
    chat_ids = body.get("chatIds", [])
    room_name = str(body.get("roomName", "Board Room"))
    room_id = str(body.get("roomId", ""))
    game_type = str(body.get("gameType", "chess"))
    player_count = int(body.get("playerCount", 1))
    spectator_count = int(body.get("spectatorCount", 0))
    creator_name = str(body.get("creatorName", "Someone"))

    if not chat_ids or not room_id:
        return web.json_response({"error": "chatIds and roomId required"}, status=400)

    app_link = get_webapp_deep_link(bot)
    game_label = "Шахматы" if game_type == "chess" else "Шашки"

    text = (
        f"♟️ <b>{game_label} — {room_name}</b>\n\n"
        f"👤 {creator_name} приглашает в матч\n"
        f"👥 Игроков: {player_count} · 👀 Зрителей: {spectator_count}"
    )

    reply_markup = None
    if app_link:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Войти в матч", url=app_link)]
        ])

    sent = {}
    for cid in chat_ids:
        try:
            msg = await bot.send_message(chat_id=cid, text=text, parse_mode="HTML", reply_markup=reply_markup)
            sent[cid] = msg.message_id
        except Exception:
            logger.warning("Failed to send boardgame invite to chat %s", cid)

    if room_id not in _boardgame_invitation_messages:
        _boardgame_invitation_messages[room_id] = {}
    _boardgame_invitation_messages[room_id].update(sent)
    return web.json_response({"sent": len(sent)})


async def handle_boardgame_invite_update(request: web.Request):
    bot = request.app.get("bot")
    if not bot:
        return web.json_response({"error": "Bot not available"}, status=503)

    body = await request.json()
    room_id = str(body.get("roomId", ""))
    room_name = str(body.get("roomName", "Board Room"))
    game_type = str(body.get("gameType", "chess"))
    player_count = int(body.get("playerCount", 1))
    spectator_count = int(body.get("spectatorCount", 0))

    msgs = _boardgame_invitation_messages.get(room_id, {})
    if not msgs:
        return web.json_response({"updated": 0})

    app_link = get_webapp_deep_link(bot)
    game_label = "Шахматы" if game_type == "chess" else "Шашки"

    text = (
        f"♟️ <b>{game_label} — {room_name}</b>\n\n"
        f"👥 Игроков: {player_count}\n"
        f"👀 Зрителей: {spectator_count}\n"
        f"{'🟢 Есть места' if player_count < 2 else '🔴 Идёт матч'}"
    )

    reply_markup = None
    if app_link:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Войти в матч", url=app_link)]
        ])

    updated = 0
    for cid, mid in list(msgs.items()):
        try:
            await bot.edit_message_text(chat_id=cid, message_id=mid, text=text, parse_mode="HTML", reply_markup=reply_markup)
            updated += 1
        except Exception:
            pass

    return web.json_response({"updated": updated})


async def handle_boardgame_invite_delete(request: web.Request):
    bot = request.app.get("bot")
    if not bot:
        return web.json_response({"error": "Bot not available"}, status=503)

    body = await request.json()
    room_id = str(body.get("roomId", ""))

    msgs = _boardgame_invitation_messages.pop(room_id, {})
    deleted = 0
    for cid, mid in msgs.items():
        try:
            await bot.delete_message(chat_id=cid, message_id=mid)
            deleted += 1
        except Exception:
            pass

    return web.json_response({"deleted": deleted})


async def handle_exchange(request: web.Request):
    from_currency = request.query.get("from", "BYN").upper()
    to_currency = request.query.get("to", "").upper()
    try:
        amount = float(request.query.get("amount", "1"))
    except ValueError:
        return web.json_response({"error": "invalid amount"}, status=400)

    if not to_currency:
        return web.json_response({"error": "to currency required"}, status=400)

    if from_currency == to_currency:
        return web.json_response({"result": amount, "from": from_currency, "to": to_currency})

    apis = [
        {
            "url": "https://api.coinbase.com/v2/exchange-rates",
            "params": {"currency": from_currency},
            "extract": lambda j: float(j["data"]["rates"][to_currency]),
        },
        {
            "url": "https://data-api.binance.vision/api/v3/avgPrice",
            "params": {"symbol": f"{'USDT' if from_currency == 'USD' else from_currency}{'USDT' if to_currency == 'USD' else to_currency}"},
            "extract": lambda j: float(j["price"]),
        },
    ]

    async with ClientSession() as session:
        for api in apis:
            try:
                async with session.get(api["url"], params=api["params"]) as resp:
                    data = await resp.json()
                    rate = api["extract"](data)
                    return web.json_response({
                        "result": round(rate * amount, 6),
                        "rate": round(rate, 6),
                        "from": from_currency,
                        "to": to_currency,
                        "amount": amount,
                    })
            except Exception:
                continue

    return web.json_response({"error": f"Конвертация {from_currency} → {to_currency} невозможна"}, status=404)


async def handle_translate(request: web.Request):
    body = await request.json()
    text = str(body.get("text", "")).strip()
    to_lang = str(body.get("to", "")).strip().lower()
    from_lang = str(body.get("from", "")).strip().lower() or None

    if not text:
        return web.json_response({"error": "text is required"}, status=400)
    if not to_lang:
        return web.json_response({"error": "target language is required"}, status=400)

    translate_key = environ.get("TRANSLATE_KEY_SECRET", "")
    if not translate_key:
        return web.json_response({"error": "translation service not configured"}, status=503)

    async with ClientSession() as session:
        async with session.post(
            "https://translate.api.cloud.yandex.net/translate/v2/translate",
            json={
                "texts": [text],
                "targetLanguageCode": to_lang,
                "sourceLanguageCode": from_lang,
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Api-Key {translate_key}",
            },
        ) as resp:
            data = await resp.json()
            if "message" in data and "unsupported" in data.get("message", ""):
                return web.json_response({"error": f"Язык «{to_lang}» не поддерживается"}, status=400)
            try:
                translated = data["translations"][0]["text"]
                detected = data["translations"][0].get("detectedLanguageCode", from_lang)
                return web.json_response({"text": translated, "detectedLanguage": detected})
            except (KeyError, IndexError):
                return web.json_response({"error": "translation failed"}, status=500)


async def handle_timezone(request: web.Request):
    query = request.query.get("query", "").strip()

    if not query:
        from datetime import timezone as tz_mod
        now = datetime.datetime.now(tz_mod.utc)
        return web.json_response({
            "label": "UTC",
            "time": now.strftime("%d.%m.%Y %H:%M:%S"),
            "offset": "UTC+0",
        })

    if OFFSET_RE.fullmatch(query):
        result = _time_by_offset(query)
        if result is None:
            return web.json_response({"error": "Некорректное смещение (от -12 до +14)"}, status=400)
        return web.json_response(_parse_time_html(result))

    result = _time_by_city(query)
    if result is None:
        return web.json_response({"error": f"Город «{query}» не найден"}, status=404)
    return web.json_response(_parse_time_html(result))


def _parse_time_html(html_str: str) -> dict:
    label_match = re.search(r"<b>(.+?)</b>", html_str)
    label = label_match.group(1) if label_match else ""
    clean = re.sub(r"<[^>]+>", "", html_str).strip()
    parts = clean.split("\n")
    time_line = parts[-1].strip() if len(parts) > 1 else parts[0]
    offset_match = re.search(r"\((UTC[^\)]+)\)", time_line)
    offset = offset_match.group(1) if offset_match else ""
    time_str = time_line.split("(")[0].strip() if "(" in time_line else time_line
    return {"label": label, "time": time_str, "offset": offset}


TIMEZONE_CITIES = list(CITY_TIMEZONES.keys())


async def handle_timezone_cities(request: web.Request):
    return web.json_response(TIMEZONE_CITIES)


TZ_MINSK = datetime.timezone(timedelta(hours=3))


def _serialize_reminder(r: ReminderDelayedAction, chats_map: dict) -> dict:
    gen = r.generator
    next_fire = gen.next_fire.astimezone(TZ_MINSK)
    chat_name = chats_map.get(r.chat_id, {}).get("name", str(r.chat_id))
    result = {
        "id": r.id,
        "chat_id": r.chat_id,
        "chat_name": chat_name,
        "user_id": r.user_id,
        "text": r.text,
        "next_fire": next_fire.isoformat(),
        "next_fire_fmt": next_fire.strftime("%d.%m.%Y %H:%M"),
        "created_at": r.created_at.isoformat(),
    }
    if gen.interval_seconds:
        result["interval_seconds"] = gen.interval_seconds
        result["repeat_remaining"] = gen.repeat_remaining
    if gen.days:
        result["days"] = gen.days
    return result


def _serialize_completed(r: CompletedReminder, chats_map: dict) -> dict:
    chat_name = chats_map.get(r.chat_id, {}).get("name", str(r.chat_id))
    completed = r.completed_at.astimezone(TZ_MINSK)
    return {
        "id": r.id,
        "chat_id": r.chat_id,
        "chat_name": chat_name,
        "text": r.text,
        "completed_at": completed.isoformat(),
        "completed_at_fmt": completed.strftime("%d.%m.%Y %H:%M"),
        "fired_count": r.fired_count,
    }


async def handle_reminders(request: web.Request):
    repository: Repository = request.app["repository"]
    user_id = int(request.match_info["user_id"])
    chats_map = {c.id: {"name": c.name} for c in repository.db.chats}

    active = sorted(
        [a for a in repository.db.delayed_actions
         if isinstance(a, ReminderDelayedAction) and a.user_id == user_id],
        key=lambda r: r.generator.next_fire,
    )
    completed = sorted(
        [r for r in repository.db.completed_reminders if r.user_id == user_id],
        key=lambda r: r.completed_at,
        reverse=True,
    )[:50]

    return web.json_response({
        "active": [_serialize_reminder(r, chats_map) for r in active],
        "completed": [_serialize_completed(r, chats_map) for r in completed],
    })


INTERVAL_RE = re.compile(r'^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$')


async def handle_reminder_create(request: web.Request):
    repository: Repository = request.app["repository"]
    body = await request.json()

    user_id = int(body.get("user_id", 0))
    chat_id = int(body.get("chat_id", 0))
    text = str(body.get("text", "")).strip()
    time_str = str(body.get("time", "")).strip()
    repeat = body.get("repeat")
    days = body.get("days")

    if not user_id or not chat_id:
        return web.json_response({"error": "user_id and chat_id required"}, status=400)
    if not text:
        return web.json_response({"error": "text is required"}, status=400)
    if not time_str:
        return web.json_response({"error": "time is required"}, status=400)

    now = datetime.datetime.now(datetime.timezone.utc)
    next_fire = None
    interval_seconds = None

    match = INTERVAL_RE.match(time_str)
    if match and any(match.groups()):
        d, h, m, s = (int(x or 0) for x in match.groups())
        delta = timedelta(days=d, hours=h, minutes=m, seconds=s)
        if delta.total_seconds() > 0:
            next_fire = now + delta
            interval_seconds = int(delta.total_seconds())

    if not next_fire:
        time_match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            tz = TZ_MINSK
            local_now = datetime.datetime.now(tz)
            dt = local_now.replace(hour=h, minute=m, second=0, microsecond=0)
            if dt <= local_now:
                dt += timedelta(days=1)
            next_fire = dt.astimezone(datetime.timezone.utc)
            interval_seconds = 86400

    if not next_fire:
        dt_match = re.match(r'^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s+(\d{1,2}):(\d{2})$', time_str)
        if dt_match:
            day, month, year, h, m = dt_match.groups()
            tz = TZ_MINSK
            year = int(year) if year else datetime.datetime.now(tz).year
            if year < 100:
                year += 2000
            try:
                dt = datetime.datetime(year, int(month), int(day), int(h), int(m), tzinfo=tz)
                next_fire = dt.astimezone(datetime.timezone.utc)
            except ValueError:
                return web.json_response({"error": "invalid date"}, status=400)

    if not next_fire:
        return web.json_response({"error": "Не удалось распознать время. Примеры: 10m, 2h30m, 15:30, 25.12 10:00"}, status=400)

    repeat_remaining = None
    has_repeat = False
    if repeat is not None:
        has_repeat = True
        if repeat != "*":
            repeat_remaining = int(repeat)

    if days and isinstance(days, list):
        has_repeat = True

    generator = ReminderGenerator(
        next_fire=next_fire,
        interval_seconds=interval_seconds if has_repeat else None,
        repeat_remaining=repeat_remaining,
        days=days if has_repeat else None,
    )
    generator.skip_to_allowed_day()

    reminder = ReminderDelayedAction(
        id=str(uuid.uuid4())[:8],
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        created_at=now,
        generator=generator,
    )

    repository.db.delayed_actions.append(reminder)
    await repository.save()

    chats_map = {c.id: {"name": c.name} for c in repository.db.chats}
    return web.json_response(_serialize_reminder(reminder, chats_map), status=201)


async def handle_reminder_delete(request: web.Request):
    repository: Repository = request.app["repository"]
    reminder_id = request.match_info["id"]
    user_id = int(request.query.get("user_id", "0"))

    reminder = next(
        (a for a in repository.db.delayed_actions
         if isinstance(a, ReminderDelayedAction) and a.id == reminder_id and a.user_id == user_id),
        None,
    )
    if not reminder:
        return web.json_response({"error": "not found"}, status=404)

    repository.db.delayed_actions.remove(reminder)
    await repository.save()
    return web.json_response({"ok": True})


async def handle_reminder_update(request: web.Request):
    repository: Repository = request.app["repository"]
    reminder_id = request.match_info["id"]
    body = await request.json()
    user_id = int(body.get("user_id", 0))
    new_text = str(body.get("text", "")).strip()

    if not new_text:
        return web.json_response({"error": "text is required"}, status=400)

    reminder = next(
        (a for a in repository.db.delayed_actions
         if isinstance(a, ReminderDelayedAction) and a.id == reminder_id and a.user_id == user_id),
        None,
    )
    if not reminder:
        return web.json_response({"error": "not found"}, status=404)

    reminder.text = new_text
    await repository.save()

    chats_map = {c.id: {"name": c.name} for c in repository.db.chats}
    return web.json_response(_serialize_reminder(reminder, chats_map))


MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


async def handle_birthdays(request: web.Request):
    repository: Repository = request.app["repository"]
    chat_id = int(request.query.get("chat_id", "0"))
    if chat_id:
        items = [b for b in repository.db.birthdays if b.chat_id == chat_id]
    else:
        items = list(repository.db.birthdays)

    items.sort(key=lambda b: (b.month, b.day))
    return web.json_response([
        {"name": b.name, "day": b.day, "month": b.month, "month_name": MONTHS_RU[b.month - 1], "chat_id": b.chat_id}
        for b in items
    ])


async def handle_birthday_create(request: web.Request):
    repository: Repository = request.app["repository"]
    body = await request.json()

    name = str(body.get("name", "")).strip()
    day = int(body.get("day", 0))
    month = int(body.get("month", 0))
    chat_id = int(body.get("chat_id", 0))

    if not name or not chat_id:
        return web.json_response({"error": "name and chat_id required"}, status=400)
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return web.json_response({"error": "invalid date"}, status=400)

    existing = next(
        (b for b in repository.db.birthdays if b.name == name and b.chat_id == chat_id),
        None,
    )
    if existing:
        existing.day = day
        existing.month = month
    else:
        repository.db.birthdays.append(Birthday(name, day, month, chat_id))

    await repository.save()
    return web.json_response({
        "name": name, "day": day, "month": month,
        "month_name": MONTHS_RU[month - 1], "chat_id": chat_id,
    }, status=201)


async def handle_birthday_delete(request: web.Request):
    repository: Repository = request.app["repository"]
    body = await request.json()
    name = str(body.get("name", "")).strip()
    chat_id = int(body.get("chat_id", 0))

    to_delete = next(
        (b for b in repository.db.birthdays if b.name == name and b.chat_id == chat_id),
        None,
    )
    if not to_delete:
        return web.json_response({"error": "not found"}, status=404)

    repository.db.birthdays.remove(to_delete)
    await repository.save()
    return web.json_response({"ok": True})


async def handle_chat_stats(request: web.Request):
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    chat_id = request.query.get("chat_id", "")
    period = request.query.get("period", "day")
    scope = request.query.get("scope", "chat")
    top_n = int(request.query.get("top", "15"))

    from steward.features.stats import (
        _STATS as STATS,
        _Scope as StatsScope,
        _Period as StatsPeriod,
        _period_range as stats_period_range,
        _promql, _monkey_leaderboard,
        _SCOPE_LABELS as SCOPE_LABELS,
        _PERIOD_LABELS as PERIOD_LABELS,
    )

    try:
        scope_enum = StatsScope(scope)
    except ValueError:
        scope_enum = StatsScope.CHAT
    try:
        period_enum = StatsPeriod(period)
    except ValueError:
        period_enum = StatsPeriod.DAY

    sections = []
    for stat in STATS:
        if stat.is_db:
            entries = _monkey_leaderboard(repository, scope_enum, chat_id, top_n)
            items = [{"name": name, "value": val, "emoji": "🐵"} for name, val in entries]
            sections.append({"label": stat.label, "items": items})
        else:
            try:
                result = await metrics.query(_promql(stat, scope_enum, period_enum, chat_id, top_n=top_n))
                items = [
                    {"name": s.labels.get("user_name", s.labels.get("user_id", "?")), "value": int(s.value) if s.value == int(s.value) else round(s.value, 1)}
                    for s in result
                ]
                sections.append({"label": stat.label, "items": items})
            except Exception:
                sections.append({"label": stat.label, "items": []})

    return web.json_response({
        "scope": SCOPE_LABELS.get(scope_enum, ""),
        "period": PERIOD_LABELS.get(period_enum, ""),
        "sections": sections,
    })


def _get_tg_user_from_request(request: web.Request) -> dict | None:
    init_data = request.headers.get("X-Telegram-Init-Data") or request.query.get("initData")
    if init_data:
        return _validate_telegram_init_data(init_data)
    return None


# ── /api/bills ──────────────────────────────────────────────────────────────────

def _serialize_bill_person(p) -> dict:
    return {
        "id": p.id,
        "display_name": p.display_name,
        "telegram_id": p.telegram_id,
        "telegram_username": p.telegram_username,
        "aliases": list(p.aliases),
        "description": p.description,
    }


def _serialize_assignment(asg) -> dict:
    return {
        "unit_count": asg.unit_count,
        "debtors": list(asg.debtors),
    }


def _serialize_transaction(tx) -> dict:
    return {
        "id": tx.id,
        "item_name": tx.item_name,
        "creditor": tx.creditor,
        "unit_price_minor": tx.unit_price_minor,
        "quantity": tx.quantity,
        "assignments": [_serialize_assignment(a) for a in tx.assignments],
        "added_by_person_id": tx.added_by_person_id,
        "source": tx.source,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "incomplete": tx.incomplete,
    }


def _serialize_payment_v2(p) -> dict:
    return {
        "id": p.id,
        "debtor": p.debtor,
        "creditor": p.creditor,
        "amount_minor": p.amount_minor,
        "currency": p.currency,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "bill_ids": list(p.bill_ids),
    }


def _serialize_bill_v2(bill, payments: list) -> dict:
    bill_payments = [p for p in payments if bill.id in p.bill_ids]
    return {
        "id": bill.id,
        "name": bill.name,
        "author_person_id": bill.author_person_id,
        "participants": list(bill.participants),
        "transactions": [_serialize_transaction(tx) for tx in bill.transactions],
        "currency": bill.currency,
        "origin_chat_id": bill.origin_chat_id,
        "created_at": bill.created_at.isoformat() if bill.created_at else None,
        "updated_at": bill.updated_at.isoformat() if bill.updated_at else None,
        "closed": bill.closed,
        "closed_at": bill.closed_at.isoformat() if bill.closed_at else None,
        "payments": [_serialize_payment_v2(p) for p in bill_payments],
    }


def _serialize_suggestion(s) -> dict:
    return {
        "id": s.id,
        "bill_id": s.bill_id,
        "proposed_by_person_id": s.proposed_by_person_id,
        "proposed_tx": [_serialize_transaction(tx) for tx in s.proposed_tx],
        "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "decided_by_person_id": s.decided_by_person_id,
        "decided_at": s.decided_at.isoformat() if s.decided_at else None,
    }


def _check_bill_access(
    bill,
    tg_user_id: int,
    repository: Repository,
    mode: str = "view",
) -> tuple[bool, str | None]:
    """Mode: view | edit | close | merge.
    Returns (allowed, error_message)."""
    if not tg_user_id:
        return False, "no auth"
    is_admin = repository.is_admin(tg_user_id)
    person = repository.get_bill_person_by_telegram_id(tg_user_id)
    pid = person.id if person else None

    is_author = pid is not None and pid == bill.author_person_id
    is_participant = pid is not None and pid in bill.participants

    if mode == "view":
        if is_admin or is_author or is_participant:
            return True, None
        return False, "no access"
    if mode == "edit":
        if is_admin or is_author:
            return True, None
        return False, "only author/admin can edit"
    if mode == "close" or mode == "merge":
        if is_admin or is_author:
            return True, None
        return False, "only author/admin"
    return False, "unknown mode"


def _bills_visible_for_user(repository: Repository, tg_user_id: int, scope_all: bool = False) -> list:
    person = repository.get_bill_person_by_telegram_id(tg_user_id)
    is_admin = repository.is_admin(tg_user_id)
    if scope_all and is_admin:
        user = next((u for u in repository.db.users if u.id == tg_user_id), None)
        admin_chat_ids = set(user.chat_ids) if user else set()
        return [
            b for b in repository.db.bills_v2
            if (person and (person.id == b.author_person_id or person.id in b.participants))
            or (b.origin_chat_id in admin_chat_ids)
        ]
    if person:
        return repository.get_bills_v2_for_person(person.id)
    return []


async def handle_bills_list(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    scope = request.query.get("scope", "")
    bills = _bills_visible_for_user(repository, int(tg_user["id"]), scope == "all")
    payments = repository.db.bill_payments_v2
    return web.json_response({
        "bills": [_serialize_bill_v2(b, payments) for b in bills],
        "persons": [_serialize_bill_person(p) for p in repository.db.bill_persons],
    })


async def handle_bills_get(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    bill_id = int(request.match_info["id"])
    bill = repository.get_bill_v2(bill_id)
    if not bill:
        return web.json_response({"error": "not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "view")
    if not ok:
        return web.json_response({"error": err}, status=403)
    return web.json_response(_serialize_bill_v2(bill, repository.db.bill_payments_v2))


async def handle_bills_create(request: web.Request):
    import uuid as _uuid
    from steward.data.models.bill_v2 import BillV2
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    currency = data.get("currency", "BYN")
    origin_chat_id = data.get("origin_chat_id")

    caller, _ = repository.get_or_create_bill_person(
        telegram_id=int(tg_user["id"]),
        display_name=tg_user.get("first_name") or tg_user.get("username") or str(tg_user["id"]),
        username=tg_user.get("username"),
    )
    bill = BillV2(
        id=repository.get_next_bill_v2_id(),
        name=name,
        author_person_id=caller.id,
        participants=[caller.id],
        transactions=[],
        currency=currency,
        origin_chat_id=origin_chat_id,
        updated_at=datetime.datetime.now(),
    )
    repository.db.bills_v2.append(bill)
    await repository.save()
    return web.json_response(_serialize_bill_v2(bill, repository.db.bill_payments_v2))


async def handle_bills_close(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    bill_id = int(request.match_info["id"])
    bill = repository.get_bill_v2(bill_id)
    if not bill:
        return web.json_response({"error": "not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "close")
    if not ok:
        return web.json_response({"error": err}, status=403)
    bill.closed = True
    bill.closed_at = datetime.datetime.now()
    bill.updated_at = datetime.datetime.now()
    await repository.save()
    return web.json_response(_serialize_bill_v2(bill, repository.db.bill_payments_v2))


async def handle_bills_reopen(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    bill_id = int(request.match_info["id"])
    bill = repository.get_bill_v2(bill_id)
    if not bill:
        return web.json_response({"error": "not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "close")
    if not ok:
        return web.json_response({"error": err}, status=403)
    bill.closed = False
    bill.closed_at = None
    bill.updated_at = datetime.datetime.now()
    await repository.save()
    return web.json_response(_serialize_bill_v2(bill, repository.db.bill_payments_v2))


async def handle_bills_tx_add(request: web.Request):
    import uuid as _uuid
    from steward.data.models.bill_v2 import BillTransaction, BillItemAssignment, UNKNOWN_PERSON_ID
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    bill_id = int(request.match_info["id"])
    bill = repository.get_bill_v2(bill_id)
    if not bill:
        return web.json_response({"error": "not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "edit")
    if not ok:
        return web.json_response({"error": err}, status=403)
    if bill.closed:
        return web.json_response({"error": "bill closed"}, status=400)

    data = await request.json()
    assignments_raw = data.get("assignments", [])
    assignments = [
        BillItemAssignment(unit_count=int(a.get("unit_count", 1)), debtors=list(a.get("debtors", [])))
        for a in assignments_raw
    ]
    quantity = int(data.get("quantity", sum(a.unit_count for a in assignments) or 1))
    incomplete = any(not a.debtors for a in assignments)
    tx = BillTransaction(
        id=str(_uuid.uuid4()),
        item_name=data.get("item_name", ""),
        creditor=data.get("creditor") or UNKNOWN_PERSON_ID,
        unit_price_minor=int(data.get("unit_price_minor", 0)),
        quantity=quantity,
        assignments=assignments,
        source=data.get("source", "manual"),
        incomplete=incomplete,
    )
    bill.transactions.append(tx)
    # Add new participants from assignments
    for asg in assignments:
        for d in asg.debtors:
            if d and d != UNKNOWN_PERSON_ID and d not in bill.participants:
                bill.participants.append(d)
    if tx.creditor and tx.creditor != UNKNOWN_PERSON_ID and tx.creditor not in bill.participants:
        bill.participants.append(tx.creditor)
    bill.updated_at = datetime.datetime.now()
    await repository.save()
    return web.json_response(_serialize_transaction(tx))


async def handle_bills_tx_update(request: web.Request):
    from steward.data.models.bill_v2 import BillItemAssignment
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    bill_id = int(request.match_info["id"])
    tx_id = request.match_info["tid"]
    bill = repository.get_bill_v2(bill_id)
    if not bill:
        return web.json_response({"error": "not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "edit")
    if not ok:
        return web.json_response({"error": err}, status=403)

    tx = next((t for t in bill.transactions if t.id == tx_id), None)
    if not tx:
        return web.json_response({"error": "tx not found"}, status=404)

    data = await request.json()
    if "item_name" in data:
        tx.item_name = data["item_name"]
    if "unit_price_minor" in data:
        tx.unit_price_minor = int(data["unit_price_minor"])
    if "quantity" in data:
        tx.quantity = int(data["quantity"])
    if "creditor" in data:
        tx.creditor = data["creditor"]
    if "assignments" in data:
        tx.assignments = [
            BillItemAssignment(unit_count=int(a.get("unit_count", 1)), debtors=list(a.get("debtors", [])))
            for a in data["assignments"]
        ]
        tx.incomplete = any(not a.debtors for a in tx.assignments)
    bill.updated_at = datetime.datetime.now()
    await repository.save()
    return web.json_response(_serialize_transaction(tx))


async def handle_bills_tx_delete(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    bill_id = int(request.match_info["id"])
    tx_id = request.match_info["tid"]
    bill = repository.get_bill_v2(bill_id)
    if not bill:
        return web.json_response({"error": "not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "edit")
    if not ok:
        return web.json_response({"error": err}, status=403)
    bill.transactions = [t for t in bill.transactions if t.id != tx_id]
    bill.updated_at = datetime.datetime.now()
    await repository.save()
    return web.json_response({"ok": True})


async def handle_bills_suggestions_list(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    bill_id = int(request.match_info["id"])
    bill = repository.get_bill_v2(bill_id)
    if not bill:
        return web.json_response({"error": "not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "view")
    if not ok:
        return web.json_response({"error": err}, status=403)
    suggestions = repository.get_pending_suggestions_for_bill(bill_id)
    return web.json_response([_serialize_suggestion(s) for s in suggestions])


async def handle_bills_suggestion_create(request: web.Request):
    import uuid as _uuid
    from steward.data.models.bill_v2 import (
        BillItemSuggestion,
        BillTransaction,
        BillItemAssignment,
        UNKNOWN_PERSON_ID,
    )
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    bill_id = int(request.match_info["id"])
    bill = repository.get_bill_v2(bill_id)
    if not bill or bill.closed:
        return web.json_response({"error": "not found or closed"}, status=404)

    proposer, _ = repository.get_or_create_bill_person(
        telegram_id=int(tg_user["id"]),
        display_name=tg_user.get("first_name") or tg_user.get("username") or str(tg_user["id"]),
        username=tg_user.get("username"),
    )

    data = await request.json()
    proposed_tx = []
    for raw in data.get("transactions", []):
        assignments = [
            BillItemAssignment(unit_count=int(a.get("unit_count", 1)), debtors=list(a.get("debtors", [])))
            for a in raw.get("assignments", [])
        ]
        proposed_tx.append(BillTransaction(
            id=str(_uuid.uuid4()),
            item_name=raw.get("item_name", ""),
            creditor=raw.get("creditor") or UNKNOWN_PERSON_ID,
            unit_price_minor=int(raw.get("unit_price_minor", 0)),
            quantity=int(raw.get("quantity", 1)),
            assignments=assignments,
            source=raw.get("source", "manual"),
            incomplete=any(not a.debtors for a in assignments),
        ))

    suggestion = BillItemSuggestion(
        id=str(_uuid.uuid4()),
        bill_id=bill.id,
        proposed_by_person_id=proposer.id,
        proposed_tx=proposed_tx,
        bill_updated_at_propose=bill.updated_at,
    )
    repository.db.bill_item_suggestions.append(suggestion)

    from steward.delayed_action.bill_suggestion_lifecycle import schedule_suggestion_lifecycle
    schedule_suggestion_lifecycle(repository, suggestion.id)

    await repository.save()
    return web.json_response(_serialize_suggestion(suggestion))


async def handle_bills_suggestion_approve(request: web.Request):
    import uuid as _uuid
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    sid = request.match_info["sid"]
    suggestion = repository.get_bill_suggestion(sid)
    from steward.data.models.bill_v2 import SuggestionStatus
    if not suggestion or suggestion.status != SuggestionStatus.PENDING:
        return web.json_response({"error": "not found or already decided"}, status=404)
    bill = repository.get_bill_v2(suggestion.bill_id)
    if not bill:
        return web.json_response({"error": "bill not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "edit")
    if not ok:
        return web.json_response({"error": err}, status=403)

    if suggestion.bill_updated_at_propose and bill.updated_at != suggestion.bill_updated_at_propose:
        return web.json_response({"error": "bill changed since proposal"}, status=409)

    for tx in suggestion.proposed_tx:
        tx.id = str(_uuid.uuid4())
        tx.added_by_person_id = suggestion.proposed_by_person_id
        bill.transactions.append(tx)
    if suggestion.proposed_by_person_id not in bill.participants:
        bill.participants.append(suggestion.proposed_by_person_id)
    bill.updated_at = datetime.datetime.now()
    suggestion.status = SuggestionStatus.APPROVED
    suggestion.decided_at = datetime.datetime.now()
    person = repository.get_bill_person_by_telegram_id(int(tg_user["id"]))
    suggestion.decided_by_person_id = person.id if person else None
    await repository.save()
    return web.json_response(_serialize_suggestion(suggestion))


async def handle_bills_suggestion_reject(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    sid = request.match_info["sid"]
    suggestion = repository.get_bill_suggestion(sid)
    from steward.data.models.bill_v2 import SuggestionStatus
    if not suggestion or suggestion.status != SuggestionStatus.PENDING:
        return web.json_response({"error": "not found or already decided"}, status=404)
    bill = repository.get_bill_v2(suggestion.bill_id)
    if not bill:
        return web.json_response({"error": "bill not found"}, status=404)
    ok, err = _check_bill_access(bill, int(tg_user["id"]), repository, "edit")
    if not ok:
        return web.json_response({"error": err}, status=403)
    suggestion.status = SuggestionStatus.REJECTED
    suggestion.decided_at = datetime.datetime.now()
    person = repository.get_bill_person_by_telegram_id(int(tg_user["id"]))
    suggestion.decided_by_person_id = person.id if person else None
    await repository.save()
    return web.json_response(_serialize_suggestion(suggestion))


async def handle_bills_payment_create(request: web.Request):
    import uuid as _uuid
    from steward.data.models.bill_v2 import BillPaymentV2, PaymentStatus
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    data = await request.json()

    debtor_person, _ = repository.get_or_create_bill_person(
        telegram_id=int(tg_user["id"]),
        display_name=tg_user.get("first_name") or tg_user.get("username") or str(tg_user["id"]),
        username=tg_user.get("username"),
    )
    payment = BillPaymentV2(
        id=str(_uuid.uuid4()),
        debtor=debtor_person.id,
        creditor=data["creditor"],
        amount_minor=int(data["amount_minor"]),
        currency=data.get("currency", "BYN"),
        status=PaymentStatus.PENDING,
        bill_ids=list(data.get("bill_ids", [])),
        initiated_chat_id=data.get("initiated_chat_id"),
    )
    repository.db.bill_payments_v2.append(payment)

    from steward.delayed_action.bill_payment_reminder import schedule_payment_reminder
    schedule_payment_reminder(repository, payment.id)
    await repository.save()
    return web.json_response(_serialize_payment_v2(payment))


async def handle_bills_payment_confirm(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    pid = request.match_info["pid"]
    payment = repository.get_bill_payment_v2(pid)
    from steward.data.models.bill_v2 import PaymentStatus
    if not payment or payment.status != PaymentStatus.PENDING:
        return web.json_response({"error": "not found or already decided"}, status=404)

    creditor = repository.get_bill_person(payment.creditor)
    is_admin = repository.is_admin(int(tg_user["id"]))
    if not is_admin and (not creditor or creditor.telegram_id != int(tg_user["id"])):
        return web.json_response({"error": "only creditor can confirm"}, status=403)

    payment.status = PaymentStatus.CONFIRMED
    await repository.save()
    return web.json_response(_serialize_payment_v2(payment))


async def handle_bills_payment_reject(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    pid = request.match_info["pid"]
    payment = repository.get_bill_payment_v2(pid)
    from steward.data.models.bill_v2 import PaymentStatus
    if not payment or payment.status != PaymentStatus.PENDING:
        return web.json_response({"error": "not found or already decided"}, status=404)

    creditor = repository.get_bill_person(payment.creditor)
    is_admin = repository.is_admin(int(tg_user["id"]))
    if not is_admin and (not creditor or creditor.telegram_id != int(tg_user["id"])):
        return web.json_response({"error": "only creditor can reject"}, status=403)

    payment.status = PaymentStatus.REJECTED
    await repository.save()
    return web.json_response(_serialize_payment_v2(payment))


async def handle_bills_persons(request: web.Request):
    repository: Repository = request.app["repository"]
    tg_user = _get_tg_user_from_request(request)
    if not tg_user:
        return web.json_response({"error": "auth required"}, status=401)
    return web.json_response([_serialize_bill_person(p) for p in repository.db.bill_persons])


async def handle_bills_diff_get(request: web.Request):
    repository: Repository = request.app["repository"]
    token = request.match_info["token"]
    snapshot = repository.get_bill_diff_snapshot(token)
    if not snapshot:
        return web.json_response({"error": "not found or expired"}, status=404)
    return web.json_response({
        "token": snapshot.token,
        "bill_id": snapshot.bill_id,
        "before": snapshot.before,
        "after": snapshot.after,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    })


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
    app.router.add_get("/api/exchange", handle_exchange)
    app.router.add_post("/api/translate", handle_translate)
    app.router.add_get("/api/timezone", handle_timezone)
    app.router.add_get("/api/timezone/cities", handle_timezone_cities)
    app.router.add_get("/api/reminders/{user_id}", handle_reminders)
    app.router.add_post("/api/reminders", handle_reminder_create)
    app.router.add_delete("/api/reminders/{id}", handle_reminder_delete)
    app.router.add_patch("/api/reminders/{id}", handle_reminder_update)
    app.router.add_get("/api/birthdays", handle_birthdays)
    app.router.add_post("/api/birthdays", handle_birthday_create)
    app.router.add_delete("/api/birthdays", handle_birthday_delete)
    app.router.add_get("/api/chat-stats", handle_chat_stats)
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
    app.router.add_post("/api/casino/session", handle_casino_session)
    app.router.add_get("/api/casino/balance", handle_casino_balance)
    app.router.add_post("/api/casino/event", handle_casino_event)
    app.router.add_post("/api/casino/bonus", handle_casino_bonus)
    app.router.add_get("/api/casino/stats", handle_casino_stats)
    app.router.add_get("/api/casino/rocket/init", handle_rocket_init)
    app.router.add_get("/api/casino/race/init", handle_race_init)
    app.router.add_post("/api/casino/race/bet", handle_race_bet)
    app.router.add_get("/api/casino/race/bets", handle_race_bets)
    app.router.add_get("/api/user/{user_id}/chats", handle_user_chats)
    app.router.add_post("/api/poker/invite", handle_poker_invite)
    app.router.add_post("/api/poker/invite/update", handle_poker_invite_update)
    app.router.add_post("/api/poker/invite/delete", handle_poker_invite_delete)
    app.router.add_post("/api/boardgames/invite", handle_boardgame_invite)
    app.router.add_post("/api/boardgames/invite/update", handle_boardgame_invite_update)
    app.router.add_post("/api/boardgames/invite/delete", handle_boardgame_invite_delete)
    app.router.add_get("/api/bills", handle_bills_list)
    app.router.add_post("/api/bills", handle_bills_create)
    app.router.add_get("/api/bills/persons", handle_bills_persons)
    app.router.add_get("/api/bills/diff/{token}", handle_bills_diff_get)
    app.router.add_post("/api/bills/payments", handle_bills_payment_create)
    app.router.add_put("/api/bills/payments/{pid}/confirm", handle_bills_payment_confirm)
    app.router.add_put("/api/bills/payments/{pid}/reject", handle_bills_payment_reject)
    app.router.add_post("/api/bills/suggestions/{sid}/approve", handle_bills_suggestion_approve)
    app.router.add_post("/api/bills/suggestions/{sid}/reject", handle_bills_suggestion_reject)
    app.router.add_get("/api/bills/{id}", handle_bills_get)
    app.router.add_put("/api/bills/{id}/close", handle_bills_close)
    app.router.add_put("/api/bills/{id}/reopen", handle_bills_reopen)
    app.router.add_post("/api/bills/{id}/transactions", handle_bills_tx_add)
    app.router.add_patch("/api/bills/{id}/transactions/{tid}", handle_bills_tx_update)
    app.router.add_delete("/api/bills/{id}/transactions/{tid}", handle_bills_tx_delete)
    app.router.add_get("/api/bills/{id}/suggestions", handle_bills_suggestions_list)
    app.router.add_post("/api/bills/{id}/suggestions", handle_bills_suggestion_create)
    app.router.add_get("/ws/poker", poker_ws_handler)
    app.router.add_get("/ws/blackjack", blackjack_ws_handler)
    app.router.add_get("/ws/boardgames", boardgames_ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"API server started on port {port}")
