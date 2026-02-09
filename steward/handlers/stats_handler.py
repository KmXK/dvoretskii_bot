import logging
from enum import Enum

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import CallbackBotContext, ChatBotContext
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.metrics.base import MetricSample

logger = logging.getLogger(__name__)


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

PERIOD_RANGE = {
    StatsPeriod.DAY: "24h",
    StatsPeriod.MONTH: "30d",
    StatsPeriod.ALL_TIME: "180d",
}


def _build_promql(action_type: str, scope: StatsScope, period: StatsPeriod, chat_id: str) -> str:
    label_filter = f'action_type="{action_type}"'
    if scope == StatsScope.CHAT:
        label_filter += f', chat_id="{chat_id}"'

    metric = f"bot_messages_total{{{label_filter}}}"
    expr = f"increase({metric}[{PERIOD_RANGE[period]}])"

    return f"topk(3, sum by (user_id, user_name) ({expr}))"


def _build_keyboard(scope: StatsScope, period: StatsPeriod, chat_id: str) -> InlineKeyboardMarkup:
    scope_buttons = []
    for s in StatsScope:
        text = SCOPE_LABELS[s]
        if s == scope:
            text = f"· {text} ·"
        scope_buttons.append(InlineKeyboardButton(
            text,
            callback_data=f"stats|{s.value}|{period.value}|{chat_id}",
        ))

    period_buttons = []
    for p in StatsPeriod:
        text = PERIOD_LABELS[p]
        if p == period:
            text = f"· {text} ·"
        period_buttons.append(InlineKeyboardButton(
            text,
            callback_data=f"stats|{scope.value}|{p.value}|{chat_id}",
        ))

    return InlineKeyboardMarkup([scope_buttons, period_buttons])


def _format_top(items: list[MetricSample], label: str) -> str:
    if not items:
        return f"{label}:\nНет данных"

    lines = [f"{label}:"]
    for i, item in enumerate(items, 1):
        logging.info(item.labels)
        name = item.labels.get("user_name", "???")
        value = int(item.value) if item.value == int(item.value) else round(item.value, 1)
        lines.append(f"{i}. `@{name}` — {value}")
    return "\n".join(lines)


class StatsHandler(Handler):
    async def chat(self, context: ChatBotContext) -> bool:
        if not validate_command_msg(context.update, "stats"):
            return False

        chat_id = str(context.message.chat_id)
        scope = StatsScope.CHAT
        period = StatsPeriod.DAY

        text, keyboard = await self._build_stats(scope, period, chat_id)
        await context.message.reply_markdown(text=text, reply_markup=keyboard)
        return True

    async def callback(self, context: CallbackBotContext) -> bool:
        data = context.callback_query.data
        if not data or not data.startswith("stats|"):
            return False

        parts = data.split("|")
        if len(parts) != 4:
            return False

        try:
            scope = StatsScope(parts[1])
            period = StatsPeriod(parts[2])
            chat_id = parts[3]
        except ValueError:
            return False

        text, keyboard = await self._build_stats(scope, period, chat_id)
        await context.callback_query.message.edit_text(parse_mode="markdown", text=text, reply_markup=keyboard)
        return True

    async def _build_stats(
        self,
        scope: StatsScope,
        period: StatsPeriod,
        chat_id: str,
    ) -> tuple[str, InlineKeyboardMarkup]:
        messages_top = await self.metrics.query(_build_promql("chat", scope, period, chat_id))
        reactions_top = await self.metrics.query(_build_promql("reaction", scope, period, chat_id))

        header = f"📊 {SCOPE_LABELS[scope]} | {PERIOD_LABELS[period]}"
        messages_text = _format_top(messages_top, "💬 Топ по сообщениям")
        reactions_text = _format_top(reactions_top, "❤️ Топ по реакциям")

        text = f"{header}\n\n{messages_text}\n\n{reactions_text}"
        keyboard = _build_keyboard(scope, period, chat_id)

        return text, keyboard

    def help(self):
        return "/stats — статистика чата"
