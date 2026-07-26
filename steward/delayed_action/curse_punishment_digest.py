from dataclasses import dataclass

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.helpers.class_mark import class_mark
from steward.helpers.curse_debt import (
    apply_curse_interest_until,
    build_curse_debt_report_entries,
    format_curse_debt_report,
    format_curse_interest_forecast,
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


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_punishment_digest")
class CursePunishmentDigestDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        if not context.repository.db.curse_punishments:
            return

        for chat_id in _curse_chat_ids(context.repository):
            entries = build_curse_debt_report_entries(context.repository, chat_id)
            if not entries:
                continue

            text = format_curse_debt_report(entries)
            await context.bot.send_message(chat_id, text)


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_interest_forecast")
class CurseInterestForecastDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        if not context.repository.db.curse_punishments:
            return

        for chat_id in _curse_chat_ids(context.repository):
            entries = build_curse_debt_report_entries(context.repository, chat_id)
            if not entries:
                continue

            text = format_curse_interest_forecast(entries)
            if not text:
                continue

            await context.bot.send_message(chat_id, text)


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_interest")
class CurseInterestDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        if apply_curse_interest_until(context.repository, today_msk()):
            await context.repository.save()
