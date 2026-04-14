"""8-hour payment confirmation reminder for /bills."""
import datetime
import logging
from dataclasses import dataclass

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark

logger = logging.getLogger(__name__)

REMINDER_INTERVAL_HOURS = 8


@dataclass
@class_mark("generator/bill_payment_reminder")
class BillPaymentReminderGenerator(Generator):
    fire_at: datetime.datetime

    def get_next(self, now: datetime.datetime):
        return self.fire_at


@dataclass
@class_mark("delayed_action/bill_payment_reminder")
class BillPaymentReminderAction(DelayedAction):
    payment_id: str
    generator: BillPaymentReminderGenerator

    async def execute(self, context: DelayedActionContext):
        repository = context.repository
        payment = repository.get_bill_payment_v2(self.payment_id)

        from steward.data.models.bill_v2 import PaymentStatus

        if payment is None or payment.status != PaymentStatus.PENDING:
            repository.db.delayed_actions = [a for a in repository.db.delayed_actions if a is not self]
            return

        creditor = repository.get_bill_person(payment.creditor)
        if creditor is None or creditor.telegram_id is None:
            payment.status = PaymentStatus.AUTO_CONFIRMED
            await repository.save()
            repository.db.delayed_actions = [a for a in repository.db.delayed_actions if a is not self]
            return

        debtor = repository.get_bill_person(payment.debtor)
        debtor_name = debtor.display_name if debtor else "кто-то"

        from steward.helpers.bills_diff import build_payment_reminder_phrase
        from steward.helpers.bills_money import minor_to_display
        from steward.helpers.bills_notifications import send_bill_notification
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        phrase = await build_payment_reminder_phrase(
            debtor_name=debtor_name, creditor_name=creditor.display_name,
            amount_minor=payment.amount_minor, currency=payment.currency,
        )
        amount_str = minor_to_display(payment.amount_minor, payment.currency)
        text = (
            f"💸 {debtor_name} говорит, что перевёл тебе *{amount_str}*\n\n"
            f"_{phrase}_\n\nПодтверди получение:"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Получил", callback_data=f"bills_pay_confirm|{payment.id}"),
            InlineKeyboardButton("❌ Не получал", callback_data=f"bills_pay_reject|{payment.id}"),
        ]])
        msg = await send_bill_notification(
            context.bot, repository, creditor, text,
            sender=debtor, reply_markup=kb, parse_mode="Markdown",
            initiated_chat_id=payment.initiated_chat_id,
        )
        if msg:
            payment.confirmation_chat_id = msg.chat_id
            payment.confirmation_message_id = msg.message_id
            payment.reminder_sent_at = datetime.datetime.now()
        else:
            logger.info("Cannot reach creditor %s for payment reminder", creditor.display_name)

        # Reschedule for another 8 hours
        self.generator.fire_at = datetime.datetime.now() + datetime.timedelta(hours=REMINDER_INTERVAL_HOURS)
        await repository.save()


def schedule_payment_reminder(repository, payment_id: str):
    """Add an 8h payment reminder action to delayed_actions."""
    fire_at = datetime.datetime.now() + datetime.timedelta(hours=REMINDER_INTERVAL_HOURS)
    action = BillPaymentReminderAction(
        payment_id=payment_id,
        generator=BillPaymentReminderGenerator(fire_at=fire_at),
    )
    repository.db.delayed_actions.append(action)
