"""15-minute nudge to bill author about incomplete (unassigned) transaction items."""
import datetime
import logging
from dataclasses import dataclass

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark

logger = logging.getLogger(__name__)

NUDGE_MINUTES = 15


@dataclass
@class_mark("generator/bill_incomplete_nudge")
class BillIncompleteNudgeGenerator(Generator):
    fire_at: datetime.datetime

    def get_next(self, now: datetime.datetime):
        return self.fire_at


@dataclass
@class_mark("delayed_action/bill_incomplete_nudge")
class BillIncompleteNudgeAction(DelayedAction):
    bill_id: int
    generator: BillIncompleteNudgeGenerator

    async def execute(self, context: DelayedActionContext):
        repository = context.repository

        context.repository.db.delayed_actions = [
            a for a in context.repository.db.delayed_actions if a is not self
        ]

        bill = repository.get_bill_v2(self.bill_id)
        if bill is None or bill.closed:
            await repository.save()
            return

        incomplete_txs = [tx for tx in bill.transactions if tx.incomplete]
        if not incomplete_txs:
            await repository.save()
            return

        bill.last_incomplete_reminder_at = datetime.datetime.now()

        author = repository.get_bill_person(bill.author_person_id)
        if not author or not author.telegram_id:
            await repository.save()
            return

        from steward.helpers.bills_notifications import send_bill_notification
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        names = ", ".join(f"«{tx.item_name}»" for tx in incomplete_txs[:3])
        extra = f" и ещё {len(incomplete_txs) - 3}" if len(incomplete_txs) > 3 else ""
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Открыть счёт", callback_data=f"bills:view|{bill.id}")]])
        await send_bill_notification(
            context.bot, repository, author,
            f"⚠️ В счёте «{bill.name}» есть незаполненные позиции: {names}{extra}.\nКому назначить?",
            reply_markup=kb, initiated_chat_id=bill.origin_chat_id,
        )

        await repository.save()


def schedule_incomplete_nudge(repository, bill_id: int) -> None:
    """Schedule a 15-min nudge for incomplete items in a bill."""
    # Cancel any existing nudge for this bill first
    repository.db.delayed_actions = [
        a for a in repository.db.delayed_actions
        if not (isinstance(a, BillIncompleteNudgeAction) and a.bill_id == bill_id)
    ]
    fire_at = datetime.datetime.now() + datetime.timedelta(minutes=NUDGE_MINUTES)
    action = BillIncompleteNudgeAction(
        bill_id=bill_id,
        generator=BillIncompleteNudgeGenerator(fire_at=fire_at),
    )
    repository.db.delayed_actions.append(action)
