import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from steward.bot.context import CallbackBotContext, ChatBotContext
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.metrics.base import ContextMetrics, MetricSample

logger = logging.getLogger(__name__)

MAIN_TOP_N = 3
DETAIL_TOP_N = 15
WINDOW_SIZE = 2


@dataclass
class StatMetric:
    label: str
    metric_name: str
    filters: dict[str, str] = field(default_factory=dict)


def stat(label: str, metric_name: str, **filters) -> StatMetric:
    return StatMetric(label=label, metric_name=metric_name, filters=filters)


STATS = [
    stat("💬 Топ по сообщениям", "bot_messages_total", action_type="chat"),
    stat("❤️ Топ по реакциям", "bot_messages_total", action_type="reaction"),
    stat("🎬 Топ по видосикам", "bot_downloads_total"),
]


class StatsScope(Enum):
    CHAT = "chat"
    ALL = "all"


class StatsPeriod(Enum):
    DAY = "day"
    MONTH = "month"
    ALL_TIME = "alltime"


SCOPE_LABELS = {
    StatsScope.CHAT: "Текущий чат",
    StatsScope.ALL: "Все чаты",
}

PERIOD_LABELS = {
    StatsPeriod.DAY: "Сегодня",
    StatsPeriod.MONTH: "За месяц",
    StatsPeriod.ALL_TIME: "За всё время",
}

MSK = timezone(timedelta(hours=3))


def _now_msk() -> datetime:
    return datetime.now(MSK)


def _period_range(period: StatsPeriod) -> str:
    now = _now_msk()
    if period == StatsPeriod.DAY:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return f"{max(int((now - midnight).total_seconds()), 60)}s"
    if period == StatsPeriod.MONTH:
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return f"{max(int((now - first).total_seconds()), 60)}s"
    return "540d"


def _prev_period(period: StatsPeriod) -> tuple[str, str] | None:
    now = _now_msk()
    if period == StatsPeriod.DAY:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        offset = f"{max(int((now - midnight).total_seconds()), 60)}s"
        return "86400s", offset
    if period == StatsPeriod.MONTH:
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        offset = f"{max(int((now - first).total_seconds()), 60)}s"
        prev_month_days = (first - timedelta(days=1)).day
        return f"{prev_month_days * 86400}s", offset
    return None


def _promql(
    metric: StatMetric,
    scope: StatsScope,
    period: StatsPeriod,
    chat_id: str,
    top_n: int | None = None,
    range_str: str | None = None,
    offset: str | None = None,
) -> str:
    filters = dict(metric.filters)
    if scope == StatsScope.CHAT:
        filters["chat_id"] = chat_id

    label_filter = ", ".join(f'{k}="{v}"' for k, v in filters.items())
    r = range_str or _period_range(period)
    offset_str = f" offset {offset}" if offset else ""
    expr = f"increase({metric.metric_name}{{{label_filter}}}[{r}]{offset_str})"
    agg = f"sum by (user_id, user_name) ({expr})"

    return f"topk({top_n}, {agg})" if top_n else agg


def _cb(scope: StatsScope, period: StatsPeriod, view: str, chat_id: str) -> str:
    return f"st|{scope.value}|{period.value}|{view}|{chat_id}"


def _format_line(i: int, item: MetricSample, prev_map: dict[str, float] | None = None) -> str:
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


def _scope_period_rows(
    scope: StatsScope, period: StatsPeriod, view: str, chat_id: str,
) -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(
                f"· {SCOPE_LABELS[s]} ·" if s == scope else SCOPE_LABELS[s],
                callback_data=_cb(s, period, view, chat_id),
            )
            for s in StatsScope
        ],
        [
            InlineKeyboardButton(
                f"· {PERIOD_LABELS[p]} ·" if p == period else PERIOD_LABELS[p],
                callback_data=_cb(scope, p, view, chat_id),
            )
            for p in StatsPeriod
        ],
    ]


class StatsHandler(Handler):
    async def chat(self, context: ChatBotContext) -> bool:
        if not validate_command_msg(context.update, "stats"):
            return False

        chat_id = str(context.message.chat_id)
        text, keyboard = await self._build_main(context.metrics, StatsScope.CHAT, StatsPeriod.DAY, 0, chat_id)
        await context.message.reply_markdown(text=text, reply_markup=keyboard)
        return True

    async def callback(self, context: CallbackBotContext) -> bool:
        data = context.callback_query.data
        if not data or not data.startswith("st|"):
            return False

        parts = data.split("|")
        if len(parts) != 5:
            return False

        try:
            scope = StatsScope(parts[1])
            period = StatsPeriod(parts[2])
            view = parts[3]
            chat_id = parts[4]
        except ValueError:
            return False

        if view.startswith("m"):
            text, keyboard = await self._build_main(context.metrics, scope, period, int(view[1:]), chat_id)
        elif view.startswith("d"):
            text, keyboard = await self._build_detail(context.metrics, scope, period, int(view[1:]), chat_id)
        else:
            return False

        try:
            await context.callback_query.message.edit_text(
                text=text, parse_mode="markdown", reply_markup=keyboard,
            )
        except BadRequest:
            pass
        return True

    async def _build_main(
        self, metrics: ContextMetrics, scope: StatsScope, period: StatsPeriod, offset: int, chat_id: str,
    ) -> tuple[str, InlineKeyboardMarkup]:
        n = len(STATS)
        indices = [(offset + i) % n for i in range(min(WINDOW_SIZE, n))]

        sections = []
        for i in indices:
            result = await metrics.query(_promql(STATS[i], scope, period, chat_id, top_n=MAIN_TOP_N))
            sections.append(_format_section(result, STATS[i].label))

        header = f"📊 {SCOPE_LABELS[scope]} | {PERIOD_LABELS[period]}"
        text = header + "\n\n" + "\n\n".join(sections)

        rows = _scope_period_rows(scope, period, f"m{offset}", chat_id)

        rows.append([
            InlineKeyboardButton(
                STATS[i].label,
                callback_data=_cb(scope, period, f"d{i}", chat_id),
            )
            for i in indices
        ])

        if n > WINDOW_SIZE:
            rows.append([
                InlineKeyboardButton("‹", callback_data=_cb(scope, period, f"m{(offset - 1) % n}", chat_id)),
                InlineKeyboardButton("›", callback_data=_cb(scope, period, f"m{(offset + 1) % n}", chat_id)),
            ])

        return text, InlineKeyboardMarkup(rows)

    async def _build_detail(
        self, metrics: ContextMetrics, scope: StatsScope, period: StatsPeriod, idx: int, chat_id: str,
    ) -> tuple[str, InlineKeyboardMarkup]:
        if idx < 0 or idx >= len(STATS):
            return "Метрика не найдена", InlineKeyboardMarkup([])

        m = STATS[idx]

        current = await metrics.query(_promql(m, scope, period, chat_id, top_n=DETAIL_TOP_N))

        prev_map: dict[str, float] | None = None
        prev = _prev_period(period)
        if prev:
            prev_range, prev_offset = prev
            prev_results = await metrics.query(
                _promql(m, scope, period, chat_id, range_str=prev_range, offset=prev_offset),
            )
            prev_map = {s.labels.get("user_id", ""): s.value for s in prev_results}

        header = f"{m.label}\n{SCOPE_LABELS[scope]} | {PERIOD_LABELS[period]}"

        if not current:
            text = f"{header}\n\nНет данных"
        else:
            lines = [header, ""]
            for i, item in enumerate(current, 1):
                lines.append(_format_line(i, item, prev_map))
            text = "\n".join(lines)

        rows = _scope_period_rows(scope, period, f"d{idx}", chat_id)
        rows.append([InlineKeyboardButton("← Назад", callback_data=_cb(scope, period, f"m{idx}", chat_id))])

        return text, InlineKeyboardMarkup(rows)

    def help(self):
        return "/stats — статистика чата"
