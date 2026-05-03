import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from telegram.error import BadRequest

from steward.data.repository import Repository
from steward.framework import (
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    on_callback,
    subcommand,
)
from steward.metrics.base import ContextMetrics, MetricSample

logger = logging.getLogger(__name__)

MAIN_TOP_N = 3
DETAIL_TOP_N = 15
WINDOW_SIZE = 2


@dataclass
class _StatMetric:
    label: str
    metric_name: str
    filters: dict[str, str] = field(default_factory=dict)
    is_db: bool = False


def _stat(label: str, metric_name: str, **filters) -> _StatMetric:
    return _StatMetric(label=label, metric_name=metric_name, filters=filters)


_STATS = [
    _stat("💬 Топ по сообщениям", "bot_messages_total", action_type="chat"),
    _stat("❤️ Топ по реакциям", "bot_messages_total", action_type="reaction"),
    _stat("🤬 Топ по мату", "bot_curse_words_total"),
    _stat("🎬 Топ по видосикам", "bot_downloads_total"),
    _StatMetric(label="🐵 Топ по обезьянкам", metric_name="", is_db=True),
]


class _Scope(Enum):
    CHAT = "chat"
    ALL = "all"


class _Period(Enum):
    DAY = "day"
    MONTH = "month"
    ALL_TIME = "alltime"


_SCOPE_LABELS = {_Scope.CHAT: "Текущий чат", _Scope.ALL: "Все чаты"}
_PERIOD_LABELS = {
    _Period.DAY: "Сегодня",
    _Period.MONTH: "За месяц",
    _Period.ALL_TIME: "За всё время",
}
_MSK = timezone(timedelta(hours=3))


def _now_msk() -> datetime:
    return datetime.now(_MSK)


def _period_range(period: _Period) -> str:
    now = _now_msk()
    if period == _Period.DAY:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return f"{max(int((now - midnight).total_seconds()), 60)}s"
    if period == _Period.MONTH:
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return f"{max(int((now - first).total_seconds()), 60)}s"
    return "540d"


def _prev_period(period: _Period) -> tuple[str, str] | None:
    now = _now_msk()
    if period == _Period.DAY:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        offset = f"{max(int((now - midnight).total_seconds()), 60)}s"
        return "86400s", offset
    if period == _Period.MONTH:
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        offset = f"{max(int((now - first).total_seconds()), 60)}s"
        prev_month_days = (first - timedelta(days=1)).day
        return f"{prev_month_days * 86400}s", offset
    return None


def _promql(
    metric: _StatMetric,
    scope: _Scope,
    period: _Period,
    chat_id: int,
    top_n: int | None = None,
    range_str: str | None = None,
    offset: str | None = None,
) -> str:
    filters = dict(metric.filters)
    if scope == _Scope.CHAT:
        filters["chat_id"] = str(chat_id)
    label_filter = ", ".join(f'{k}="{v}"' for k, v in filters.items())
    r = range_str or _period_range(period)
    offset_str = f" offset {offset}" if offset else ""
    expr = f"increase({metric.metric_name}{{{label_filter}}}[{r}]{offset_str})"
    agg = f"sum by (user_id, user_name) ({expr})"
    return f"topk({top_n}, {agg})" if top_n else agg


def _format_line(
    i: int, item: MetricSample, prev_map: dict[str, float] | None = None
) -> str:
    name = item.labels.get("user_name", f"@{item.labels.get('user_id', '???')}")
    value = int(item.value) if item.value == int(item.value) else round(item.value, 1)
    line = f"{i}. `@{name}` — {value}"
    if prev_map is not None:
        prev_val = prev_map.get(item.labels.get("user_id", ""))
        if prev_val and prev_val > 0:
            pct = (item.value - prev_val) / prev_val * 100
            sign = "+" if pct >= 0 else ""
            line += f" ({sign}{pct:.1f}%)"
    return line


def _format_section(items: list[MetricSample], label: str) -> str:
    if not items:
        return f"{label}:\nНет данных"
    lines = [f"{label}:"]
    for i, item in enumerate(items, 1):
        lines.append(_format_line(i, item))
    return "\n".join(lines)


def _monkey_leaderboard(repo: Repository, scope: _Scope, chat_id: int, top_n: int):
    users = repo.db.users
    if scope == _Scope.CHAT:
        users = [u for u in users if chat_id in u.chat_ids]
    ranked = sorted(users, key=lambda u: u.monkeys, reverse=True)[:top_n]
    return [(u.username or str(u.id), u.monkeys) for u in ranked if u.monkeys > 0]


def _format_monkey_section(entries: list[tuple[str, int]], label: str) -> str:
    if not entries:
        return f"{label}:\nНет данных"
    lines = [f"{label}:"]
    for i, (name, val) in enumerate(entries, 1):
        lines.append(f"{i}. `@{name}` — {val} 🐵")
    return "\n".join(lines)


class StatsFeature(Feature):
    command = "stats"
    description = "Статистика чата"
    help_examples = ["«покажи статистику» → /stats", "«статистика чата» → /stats"]

    @subcommand("", description="Открыть статистику")
    async def show(self, ctx: FeatureContext):
        text, kb = await self._build_main(
            ctx, _Scope.CHAT, _Period.DAY, 0, ctx.chat_id
        )
        await ctx.reply(text, keyboard=kb)

    @on_callback(
        "stats:main",
        schema="<scope:literal[chat|all]>|<period:literal[day|month|alltime]>|<offset:int>|<chat_id:int>",
    )
    async def on_main(
        self,
        ctx: FeatureContext,
        scope: str,
        period: str,
        offset: int,
        chat_id: int,
    ):
        text, kb = await self._build_main(
            ctx, _Scope(scope), _Period(period), offset, chat_id
        )
        try:
            await ctx.edit(text, keyboard=kb)
        except BadRequest:
            pass

    @on_callback(
        "stats:detail",
        schema="<scope:literal[chat|all]>|<period:literal[day|month|alltime]>|<idx:int>|<chat_id:int>",
    )
    async def on_detail(
        self,
        ctx: FeatureContext,
        scope: str,
        period: str,
        idx: int,
        chat_id: int,
    ):
        text, kb = await self._build_detail(
            ctx, _Scope(scope), _Period(period), idx, chat_id
        )
        try:
            await ctx.edit(text, keyboard=kb)
        except BadRequest:
            pass

    def _switch_rows(
        self,
        scope: _Scope,
        period: _Period,
        view: str,
        view_offset: int,
        chat_id: int,
    ) -> list[list[Button]]:
        cb_main = self.cb("stats:main")
        cb_detail = self.cb("stats:detail")

        def cb(s: _Scope, p: _Period) -> str:
            if view == "main":
                return cb_main(scope=s.value, period=p.value, offset=view_offset, chat_id=chat_id)
            return cb_detail(scope=s.value, period=p.value, idx=view_offset, chat_id=chat_id)

        return [
            [
                Button(
                    text=f"· {_SCOPE_LABELS[s]} ·" if s == scope else _SCOPE_LABELS[s],
                    callback_data=cb(s, period),
                )
                for s in _Scope
            ],
            [
                Button(
                    text=f"· {_PERIOD_LABELS[p]} ·" if p == period else _PERIOD_LABELS[p],
                    callback_data=cb(scope, p),
                )
                for p in _Period
            ],
        ]

    async def _build_main(
        self,
        ctx: FeatureContext,
        scope: _Scope,
        period: _Period,
        offset: int,
        chat_id: int,
    ) -> tuple[str, Keyboard]:
        n = len(_STATS)
        indices = [(offset + i) % n for i in range(min(WINDOW_SIZE, n))]
        sections = []
        for i in indices:
            s = _STATS[i]
            if s.is_db:
                entries = _monkey_leaderboard(ctx.repository, scope, chat_id, MAIN_TOP_N)
                sections.append(_format_monkey_section(entries, s.label))
            else:
                result = await ctx.metrics.query(
                    _promql(s, scope, period, chat_id, top_n=MAIN_TOP_N)
                )
                sections.append(_format_section(result, s.label))
        header = f"📊 {_SCOPE_LABELS[scope]} | {_PERIOD_LABELS[period]}"
        text = header + "\n\n" + "\n\n".join(sections)
        rows = self._switch_rows(scope, period, "main", offset, chat_id)
        cb_detail = self.cb("stats:detail")
        rows.append([
            Button(
                _STATS[i].label,
                callback_data=cb_detail(
                    scope=scope.value, period=period.value, idx=i, chat_id=chat_id
                ),
            )
            for i in indices
        ])
        if n > WINDOW_SIZE:
            cb_main = self.cb("stats:main")
            rows.append([
                Button(
                    "‹",
                    callback_data=cb_main(
                        scope=scope.value, period=period.value,
                        offset=(offset - 1) % n, chat_id=chat_id,
                    ),
                ),
                Button(
                    "›",
                    callback_data=cb_main(
                        scope=scope.value, period=period.value,
                        offset=(offset + 1) % n, chat_id=chat_id,
                    ),
                ),
            ])
        return text, Keyboard.grid(rows)

    async def _build_detail(
        self,
        ctx: FeatureContext,
        scope: _Scope,
        period: _Period,
        idx: int,
        chat_id: int,
    ) -> tuple[str, Keyboard]:
        if idx < 0 or idx >= len(_STATS):
            return "Метрика не найдена", Keyboard([])
        m = _STATS[idx]
        if m.is_db:
            entries = _monkey_leaderboard(ctx.repository, scope, chat_id, DETAIL_TOP_N)
            header = f"{m.label}\n{_SCOPE_LABELS[scope]}"
            if not entries:
                text = f"{header}\n\nНет данных"
            else:
                lines = [header, ""]
                for i, (name, val) in enumerate(entries, 1):
                    lines.append(f"{i}. `@{name}` — {val} 🐵")
                text = "\n".join(lines)
        else:
            current = await ctx.metrics.query(
                _promql(m, scope, period, chat_id, top_n=DETAIL_TOP_N)
            )
            prev_map: dict[str, float] | None = None
            prev = _prev_period(period)
            if prev:
                prev_range, prev_offset = prev
                prev_results = await ctx.metrics.query(
                    _promql(m, scope, period, chat_id, range_str=prev_range, offset=prev_offset)
                )
                prev_map = {s.labels.get("user_id", ""): s.value for s in prev_results}
            header = f"{m.label}\n{_SCOPE_LABELS[scope]} | {_PERIOD_LABELS[period]}"
            if not current:
                text = f"{header}\n\nНет данных"
            else:
                lines = [header, ""]
                for i, item in enumerate(current, 1):
                    lines.append(_format_line(i, item, prev_map))
                text = "\n".join(lines)
        rows = self._switch_rows(scope, period, "detail", idx, chat_id)
        cb_main = self.cb("stats:main")
        rows.append([
            Button(
                "← Назад",
                callback_data=cb_main(
                    scope=scope.value, period=period.value, offset=idx, chat_id=chat_id
                ),
            )
        ])
        return text, Keyboard.grid(rows)
