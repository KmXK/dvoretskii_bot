from dataclasses import dataclass
from datetime import timedelta

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.helpers.class_mark import class_mark
from steward.helpers.curse_debt import (
    apply_curse_interest_until,
    build_curse_debt_report_entries,
    format_curse_day_outcome,
    format_curse_day_plan,
    today_msk,
)
from steward.helpers.curse_streak import (
    finalize_curse_streaks,
    format_curse_streak_forecast,
    format_curse_streak_outcome,
)


def _curse_chat_ids(repository) -> list[int]:
    return sorted(
        {
            chat_id
            for participant in repository.db.curse_participants
            for chat_id in participant.source_chat_ids
        }
    )


async def _broadcast_curse_report(
    context: DelayedActionContext,
    debt_formatter=None,
    streak_formatter=None,
) -> None:
    for chat_id in _curse_chat_ids(context.repository):
        sections: list[str] = []
        if debt_formatter is not None:
            entries = build_curse_debt_report_entries(context.repository, chat_id)
            if entries:
                text = debt_formatter(entries)
                if text:
                    sections.append(text)
        if streak_formatter is not None:
            text = streak_formatter(context.repository, chat_id)
            if text:
                sections.append(text)
        if not sections:
            continue
        await context.bot.send_message(chat_id, "\n\n".join(sections), parse_mode="HTML")


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
        today = today_msk()
        await _broadcast_curse_report(
            context,
            format_curse_day_plan if context.repository.db.curse_punishments else None,
            lambda repository, chat_id: format_curse_streak_forecast(
                repository, chat_id, today
            ),
        )


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_interest")
class CurseInterestDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        today = today_msk()
        debt_changed = apply_curse_interest_until(context.repository, today)
        outcomes = finalize_curse_streaks(
            context.repository,
            today - timedelta(days=1),
        )
        if not debt_changed and not outcomes:
            return

        await context.repository.save()
        await _broadcast_curse_report(
            context,
            format_curse_day_outcome if debt_changed else None,
            lambda repository, chat_id: format_curse_streak_outcome(
                repository, chat_id, outcomes
            ),
        )
