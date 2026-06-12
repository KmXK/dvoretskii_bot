"""Динамический обозреватель метрик для вебаппа.

Каталог метрик строится из реально существующих рядов в VictoriaMetrics,
поэтому новые метрики появляются в вебаппе сами. Видимость считается
только на сервере: юзер видит ряды своих чатов, свои собственные
(user_id == viewer) и людей, с кем состоит в одном чате. Метрики без
chat_id/user_id лейблов видят только админы. Клиент не передаёт PromQL.
"""

import asyncio
import datetime
import logging
import re
from datetime import timezone
from os import environ

import aiohttp
from aiohttp import web

from steward.api.auth import session_user_id
from steward.data.repository import Repository
from steward.metrics.base import MetricsEngine

logger = logging.getLogger(__name__)

_CATALOG_LOOKBACK = "180d"
_NOISE_PREFIXES = ("python_", "process_", "go_", "scrape_", "vm", "flag")
# *_created — авто-близнецы счётчиков prometheus_client со значением-таймстампом
_NOISE_SUFFIXES = ("_created", "_bucket")
_NOISE_EXACT = {"up"}
_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")

_METRIC_META = {
    "bot_messages_total": ("Сообщения", "💬"),
    "bot_downloads_total": ("Скачивания", "🎬"),
    "bot_curse_words_total": ("Маты", "🤬"),
    "bot_curse_punishment_done_total": ("Наказания", "👮"),
    "poker_games_total": ("Покер: игры", "🃏"),
    "poker_games_won_total": ("Покер: победы", "🏆"),
    "poker_hands_total": ("Покер: руки", "🃏"),
    "poker_combinations_total": ("Покер: комбинации", "🎴"),
    "poker_combinations_won_total": ("Покер: победные комбо", "🎴"),
    "poker_chips_won_total": ("Покер: фишки выиграно", "🪙"),
    "poker_chips_lost_total": ("Покер: фишки проиграно", "🪙"),
    "casino_games_total": ("Казино: игры", "🎰"),
    "casino_monkeys_bet_total": ("Обезьянки: ставки", "🐵"),
    "casino_monkeys_won_total": ("Обезьянки: выигрыши", "🐵"),
    "casino_bonus_total": ("Казино: бонусы", "🎁"),
    "bot_handler_calls_total": ("Вызовы хендлеров", "⚙️"),
}

_WINDOWS = {
    "day": (86400, 1800),
    "3d": (3 * 86400, 3 * 3600),
    "week": (7 * 86400, 6 * 3600),
    "month": (30 * 86400, 86400),
    "quarter": (90 * 86400, 3 * 86400),
    "year": (365 * 86400, 7 * 86400),
}
_STEPS = [600, 1800, 3600, 6 * 3600, 86400, 7 * 86400]
_MAX_BUCKETS = 500
_MAX_METRICS = 8
_MAX_SERIES = 20


def _is_noise(name: str) -> bool:
    return (
        name in _NOISE_EXACT
        or name.startswith(_NOISE_PREFIXES)
        or name.endswith(_NOISE_SUFFIXES)
    )


def _metric_meta(name: str) -> tuple[str, str, bool]:
    if name in _METRIC_META:
        label, emoji = _METRIC_META[name]
        return label, emoji, True
    pretty = name.removeprefix("bot_").removesuffix("_total").replace("_", " ").capitalize()
    return pretty, "📊", False


def _viewer_acl(repo: Repository, viewer_id: int) -> tuple[set[int], set[int], bool]:
    user = next((u for u in repo.db.users if u.id == viewer_id), None)
    chats = set(user.chat_ids or ()) if user else set()
    users = {viewer_id}
    for u in repo.db.users:
        if u.chat_ids and chats & set(u.chat_ids):
            users.add(u.id)
    return chats, users, repo.is_admin(viewer_id)


def _sample_visible(
    labels: dict[str, str],
    chats: set[int],
    users: set[int],
    viewer_id: int,
    admin: bool,
) -> bool:
    if admin:
        return True
    chat_id = labels.get("chat_id")
    user_id = labels.get("user_id")
    if chat_id:
        if chat_id == "inline":
            return user_id == str(viewer_id)
        try:
            return int(chat_id) in chats
        except ValueError:
            return False
    if user_id:
        try:
            return int(user_id) in users
        except ValueError:
            return False
    return False


async def _discover(metrics: MetricsEngine, name_regex: str):
    promql = (
        f"group by (__name__, chat_id, user_id) "
        f'(last_over_time({{__name__=~"{name_regex}"}}[{_CATALOG_LOOKBACK}]))'
    )
    return await metrics.query(promql)


def _collect_metric_info(
    samples,
    chats: set[int],
    users: set[int],
    viewer_id: int,
    admin: bool,
) -> dict[str, dict]:
    info: dict[str, dict] = {}
    for s in samples:
        name = s.labels.get("__name__", "")
        if not name or _is_noise(name):
            continue
        entry = info.setdefault(name, {"has_chat": False, "has_user": False, "visible": False})
        if s.labels.get("chat_id"):
            entry["has_chat"] = True
        if s.labels.get("user_id"):
            entry["has_user"] = True
        if _sample_visible(s.labels, chats, users, viewer_id, admin):
            entry["visible"] = True
    return {name: e for name, e in info.items() if e["visible"]}


async def handle_metrics_catalog(request: web.Request):
    """Список метрик, видимых текущему юзеру. Динамический — из живых рядов VM."""
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    viewer_id = session_user_id(request)
    if viewer_id is None:
        return web.json_response({"error": "unauthorized"}, status=401)

    chats, users, admin = _viewer_acl(repository, viewer_id)
    try:
        samples = await _discover(metrics, ".+")
    except Exception:
        logger.exception("metrics catalog discovery failed")
        samples = []

    info = _collect_metric_info(samples, chats, users, viewer_id, admin)

    known_order = {name: i for i, name in enumerate(_METRIC_META)}
    items = []
    for name in sorted(info, key=lambda n: (known_order.get(n, len(known_order)), n)):
        label, emoji, known = _metric_meta(name)
        items.append({
            "name": name,
            "label": label,
            "emoji": emoji,
            "known": known,
            "has_chat": info[name]["has_chat"],
            "has_user": info[name]["has_user"],
        })

    def _user_label(u) -> str:
        return u.first_name or (f"@{u.username}" if u.username else str(u.id))

    chat_items = [
        {"id": c.id, "name": c.name}
        for c in repository.db.chats
        if admin or c.id in chats
    ]
    chat_items.sort(key=lambda c: c["name"].lower())
    user_items = [
        {"id": u.id, "name": _user_label(u)}
        for u in repository.db.users
        if admin or u.id in users
    ]
    user_items.sort(key=lambda u: u["name"].lower())

    return web.json_response({
        "metrics": items,
        "chats": chat_items,
        "users": user_items,
        "is_admin": admin,
    })


def _ids_regex(ids: set[int]) -> str:
    return "|".join(str(i) for i in sorted(ids))


def _parse_ids(raw: str) -> set[int]:
    out = set()
    for token in raw.split(","):
        try:
            out.add(int(token))
        except ValueError:
            continue
    return out


def _metric_exprs(
    name: str,
    entry: dict,
    eff_chats: set[int] | None,
    eff_users: set[int] | None,
    viewer_id: int,
    admin: bool,
    step_seconds: int,
    chat_filtered: bool,
    user_filtered: bool,
) -> list[str]:
    """eff_* == None — без ограничения (только у админа), пустой set — пусто."""
    rng = f"[{step_seconds}s]"
    if chat_filtered and not entry["has_chat"]:
        return []
    if user_filtered and not entry["has_user"]:
        return []
    if admin and eff_chats is None and eff_users is None:
        return [f"increase({name}{rng})"]

    exprs = []
    if entry["has_chat"]:
        parts = []
        skip_main = False
        if eff_chats is not None:
            if eff_chats:
                parts.append(f'chat_id=~"{_ids_regex(eff_chats)}"')
            else:
                skip_main = True
        if eff_users is not None and user_filtered:
            if eff_users:
                parts.append(f'user_id=~"{_ids_regex(eff_users)}"')
            else:
                skip_main = True
        if not skip_main:
            sel = "{" + ", ".join(parts) + "}" if parts else ""
            exprs.append(f"increase({name}{sel}{rng})")
        if not chat_filtered and not admin:
            if not user_filtered or (eff_users and viewer_id in eff_users):
                exprs.append(
                    f'increase({name}{{chat_id="inline",user_id="{viewer_id}"}}{rng})'
                )
    elif entry["has_user"]:
        if eff_users is None:
            exprs.append(f"increase({name}{rng})")
        elif eff_users:
            exprs.append(f'increase({name}{{user_id=~"{_ids_regex(eff_users)}"}}{rng})')
    elif admin:
        exprs.append(f"increase({name}{rng})")
    return exprs


def _round(v: float):
    return int(v) if v == int(v) else round(v, 1)


async def handle_metrics_range(request: web.Request):
    """Timeseries по метрикам с разбивкой.

    Params:
      metrics  comma-separated имена метрик (обязателен)
      mode     metric|chat|user   (metric — линия на метрику; chat/user —
               линия на чат/человека, значения суммируются по всем метрикам)
      period   day|3d|week|month|quarter|year
      start    unix-секунды — произвольный интервал (вместе с end, важнее period)
      end      unix-секунды
      step     секунды из _STEPS (default: auto by period/интервалу)
      chats    comma-separated chat_id — сузить до этих чатов (пересекается с ACL)
      users    comma-separated user_id — сузить до этих людей (пересекается с ACL)
      limit    максимум линий, 1..20 (default 10)
      rank     max|avg|min — критерий отбора топа (default max)
    """
    repository: Repository = request.app["repository"]
    metrics: MetricsEngine = request.app["metrics"]
    viewer_id = session_user_id(request)
    if viewer_id is None:
        return web.json_response({"error": "unauthorized"}, status=401)

    requested = [
        m for m in request.query.get("metrics", "").split(",")
        if m and _NAME_RE.match(m) and not _is_noise(m)
    ][:_MAX_METRICS]
    if not requested:
        return web.json_response({"error": "metrics required"}, status=400)

    mode = request.query.get("mode", "metric")
    if mode not in ("metric", "chat", "user"):
        mode = "metric"

    try:
        limit = max(1, min(int(request.query.get("limit", "10")), _MAX_SERIES))
    except ValueError:
        limit = 10
    rank = request.query.get("rank", "max")
    if rank not in ("max", "avg", "min"):
        rank = "max"

    now = int(datetime.datetime.now(tz=timezone.utc).timestamp())

    period = request.query.get("period", "week")
    custom = None
    try:
        custom_start = int(request.query.get("start", "0"))
        custom_end = int(request.query.get("end", "0"))
        if custom_start > 0 and custom_end > custom_start:
            custom = (custom_start, min(custom_end, now))
    except ValueError:
        pass

    if custom is not None:
        period = "custom"
        window_seconds = min(custom[1] - custom[0], 400 * 86400)
        end_ts = custom[1]
        step_seconds = next(
            (s for s in _STEPS if window_seconds // s <= 200), _STEPS[-1]
        )
    else:
        if period not in _WINDOWS:
            period = "week"
        window_seconds, step_seconds = _WINDOWS[period]
        end_ts = now

    try:
        requested_step = int(request.query.get("step", "0"))
    except ValueError:
        requested_step = 0
    if requested_step in _STEPS:
        step_seconds = requested_step
    while window_seconds // step_seconds > _MAX_BUCKETS:
        bigger = [s for s in _STEPS if s > step_seconds]
        if not bigger:
            step_seconds *= 2
            continue
        step_seconds = bigger[0]

    chats, users, admin = _viewer_acl(repository, viewer_id)

    chat_filter = _parse_ids(request.query.get("chats", ""))
    user_filter = _parse_ids(request.query.get("users", ""))
    if admin:
        eff_chats = chat_filter if chat_filter else None
        eff_users = user_filter if user_filter else None
    else:
        eff_chats = chats & chat_filter if chat_filter else chats
        eff_users = users & user_filter if user_filter else users

    name_regex = "^(" + "|".join(requested) + ")$"
    try:
        samples = await _discover(metrics, name_regex)
    except Exception:
        logger.exception("metrics range discovery failed")
        samples = []
    info = _collect_metric_info(samples, chats, users, viewer_id, admin)
    visible_metrics = [m for m in requested if m in info]

    end = (end_ts // step_seconds) * step_seconds
    start = end - (window_seconds // step_seconds) * step_seconds + step_seconds
    buckets = list(range(start, end + 1, step_seconds))
    bucket_index = {ts: i for i, ts in enumerate(buckets)}

    group_by = {
        "chat": "sum by (chat_id, chat_name)",
        "user": "sum by (user_id, user_name)",
        "metric": "sum",
    }[mode]

    async def _query_metric(name: str):
        exprs = _metric_exprs(
            name, info[name], eff_chats, eff_users, viewer_id, admin,
            step_seconds, bool(chat_filter), bool(user_filter),
        )
        if not exprs:
            return name, []
        promql = f"{group_by} ({' or '.join(exprs)})"
        try:
            return name, await metrics.query_range(promql, start, end, step_seconds)
        except Exception:
            logger.exception("metrics range query failed: %s", name)
            return name, []

    results = await asyncio.gather(*(_query_metric(m) for m in visible_metrics))

    chat_names = {str(c.id): c.name for c in repository.db.chats}
    merged: dict[str, dict] = {}
    for metric_name, series_list in results:
        m_label, m_emoji, _ = _metric_meta(metric_name)
        for s in series_list:
            if mode == "chat":
                cid = s.labels.get("chat_id", "")
                if cid == "inline":
                    key, label, emoji = "inline", "Инлайн", "📥"
                else:
                    key = cid or "?"
                    label = chat_names.get(cid) or s.labels.get("chat_name") or cid or "?"
                    emoji = "💬"
            elif mode == "user":
                key = s.labels.get("user_id", "?")
                label = s.labels.get("user_name") or key
                emoji = "👤"
            else:
                key, label, emoji = metric_name, m_label, m_emoji
            entry = merged.setdefault(key, {
                "key": key,
                "label": label,
                "emoji": emoji,
                "values": [0.0] * len(buckets),
            })
            for ts, val in s.points:
                idx = bucket_index.get(int(ts))
                if idx is not None and val and val > 0:
                    entry["values"][idx] += val

    def _score(values: list[float]) -> float:
        if rank == "max":
            return max(values)
        if rank == "min":
            return min(values)
        return sum(values) / len(values)

    aggregated = []
    for entry in merged.values():
        total = sum(entry["values"])
        if total <= 0:
            continue
        entry["total"] = _round(total)
        entry["score"] = _score(entry["values"])
        entry["values"] = [_round(v) for v in entry["values"]]
        aggregated.append(entry)

    aggregated.sort(key=lambda e: (e["score"], e["total"]), reverse=True)
    top = aggregated[:limit]
    if mode == "user":
        viewer_key = str(viewer_id)
        if not any(e["key"] == viewer_key for e in top):
            mine = next((e for e in aggregated if e["key"] == viewer_key), None)
            if mine is not None:
                top.append(mine)
        for e in top:
            e["is_me"] = e["key"] == viewer_key

    for e in top:
        e.pop("score", None)

    return web.json_response({
        "mode": mode,
        "period": period,
        "step_seconds": step_seconds,
        "buckets": buckets,
        "series": top,
        "series_total": len(aggregated),
    })


_VM_PROXY_PATH_RE = re.compile(
    r"^(query|query_range|series|labels|label/[a-zA-Z_][a-zA-Z0-9_]*/values)$"
)


async def handle_metrics_vm_proxy(request: web.Request):
    """Сырой доступ к VictoriaMetrics /api/v1/* — только для админов.

    Используется scripts/vmq.sh для PromQL-запросов к проду без Grafana.
    """
    repository: Repository = request.app["repository"]
    viewer_id = session_user_id(request)
    if viewer_id is None:
        return web.json_response({"error": "unauthorized"}, status=401)
    if not repository.is_admin(viewer_id):
        return web.json_response({"error": "forbidden"}, status=403)

    vm_path = request.match_info["vm_path"]
    if not _VM_PROXY_PATH_RE.match(vm_path):
        return web.json_response({"error": "unsupported path"}, status=400)

    vm_url = environ.get("VICTORIAMETRICS_URL", "http://victoriametrics:8428")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{vm_url}/api/v1/{vm_path}",
                params=request.query,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                body = await resp.read()
                return web.Response(
                    body=body,
                    status=resp.status,
                    content_type="application/json",
                )
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.exception("VM proxy request failed: %s", vm_path)
        return web.json_response({"error": "victoriametrics unreachable"}, status=503)
