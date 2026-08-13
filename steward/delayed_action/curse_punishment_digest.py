from dataclasses import dataclass

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


def _curse_chat_ids(repository) -> list[int]:
    return sorted(
        {
            chat_id
            for participant in repository.db.curse_participants
            for chat_id in participant.source_chat_ids
        }
    )


async def _broadcast_curse_report(context: DelayedActionContext, formatter) -> None:
    for chat_id in _curse_chat_ids(context.repository):
        entries = build_curse_debt_report_entries(context.repository, chat_id)
        if not entries:
            continue

        text = formatter(entries)
        if not text:
            continue

        await context.bot.send_message(chat_id, text, parse_mode="HTML")


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
        if not context.repository.db.curse_punishments:
            return

        await _broadcast_curse_report(context, format_curse_day_plan)


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_interest")
class CurseInterestDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        if not apply_curse_interest_until(context.repository, today_msk()):
            return

        await context.repository.save()
        await _broadcast_curse_report(context, format_curse_day_outcome)
