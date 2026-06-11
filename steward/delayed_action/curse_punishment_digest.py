from dataclasses import dataclass

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.helpers.class_mark import class_mark
from steward.helpers.curse_debt import (
    apply_curse_interest_until,
    build_curse_debt_report_entries,
    format_curse_debt_report,
    today_msk,
)


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_punishment_digest")
class CursePunishmentDigestDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        if not context.repository.db.curse_punishments:
            return

        chat_ids = sorted(
            {
                chat_id
                for participant in context.repository.db.curse_participants
                for chat_id in participant.source_chat_ids
            }
        )

        if not chat_ids:
            return

        for chat_id in chat_ids:
            entries = build_curse_debt_report_entries(context.repository, chat_id)
            if not entries:
                continue

            text = format_curse_debt_report(entries)
            await context.bot.send_message(chat_id, text)


@dataclass(kw_only=True)
@class_mark("delayed_action/curse_interest")
class CurseInterestDelayedAction(DelayedAction):
    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        if apply_curse_interest_until(context.repository, today_msk()):
            await context.repository.save()
