import logging
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.helpers.class_mark import class_mark
from steward.helpers.curse_chart import build_curse_chart_series, render_curse_chart_png
from steward.helpers.curse_debt import (
    apply_curse_interest_until,
    build_curse_debt_report_entries,
    format_curse_day_outcome,
    format_curse_day_plan,
    today_msk,
)
from steward.helpers.curse_streak import (
    curse_report_chat_ids,
    finalize_curse_streaks,
)


logger = logging.getLogger(__name__)


def _curse_chat_ids(repository) -> list[int]:
    return curse_report_chat_ids(repository)


async def _send_curse_chart(
    context: DelayedActionContext,
    chat_id: int,
    chart_day: date,
) -> None:
    try:
        series = build_curse_chart_series(context.repository, chat_id, chart_day)
        chart = render_curse_chart_png(series, chart_day)
        if chart is None:
            return

        photo = BytesIO(chart)
        photo.name = f"curse-{chart_day.isoformat()}.png"
        await context.bot.send_photo(chat_id, photo=photo)
    except Exception:
        logger.exception(
            "curse hourly chart failed chat_id=%s day=%s",
            chat_id,
            chart_day,
        )


async def _broadcast_curse_report(
    context: DelayedActionContext,
    debt_formatter=None,
    chart_day: date | None = None,
) -> None:
    for chat_id in _curse_chat_ids(context.repository):
        if debt_formatter is not None:
            entries = build_curse_debt_report_entries(context.repository, chat_id)
            if entries:
                text = debt_formatter(entries)
                if text:
                    await context.bot.send_message(chat_id, text, parse_mode="HTML")
        if chart_day is not None:
            await _send_curse_chart(context, chat_id, chart_day)


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_punishment_digest")
class CursePunishmentDigestDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        return


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_interest_forecast")
class CurseInterestForecastDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        if context.repository.db.curse_punishments:
            await _broadcast_curse_report(context, format_curse_day_plan)


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_interest")
class CurseInterestDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        today = today_msk()
        debt_changed = apply_curse_interest_until(context.repository, today)
        streaks_changed = bool(
            finalize_curse_streaks(
                context.repository,
                today - timedelta(days=1),
            )
        )
        if not debt_changed and not streaks_changed:
            return

        await context.repository.save()
        await _broadcast_curse_report(
            context,
            format_curse_day_outcome if debt_changed else None,
            today - timedelta(days=1),
        )
