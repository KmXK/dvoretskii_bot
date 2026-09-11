import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from steward.data.models.bill_v2 import BillPaymentV2, BillV2, PaymentStatus
from steward.delayed_action.bill_payment_reminder import schedule_payment_reminder
from steward.framework import Keyboard
from steward.framework.callback_route import CallbackFactory, parse_schema
from steward.helpers.bills_money import compute_bill_balances, distribute_payment_amount
from steward.helpers.bills_notifications import send_bill_notification

from . import fmt

logger = logging.getLogger(__name__)

_PAY_CONFIRM = CallbackFactory(
    parse_schema("bills:pay_confirm", "<payment_id:str>")
)
_PAY_REJECT = CallbackFactory(
    parse_schema("bills:pay_reject", "<payment_id:str>")
)


@dataclass
class PaymentSettlement:
    allocations: list[tuple[int, int]]
    residual_minor: int
    auto_closed: list[BillV2]
    payments: list[BillPaymentV2]


def _bill_order_key(bill: BillV2) -> tuple[float, int]:
    created_at = bill.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return created_at.timestamp(), bill.id


def _ordered_open_bills(
    repository,
    currency: str,
    bill_ids: set[int] | None = None,
) -> list[BillV2]:
    return sorted(
        (
            bill
            for bill in repository.db.bills_v2
            if not bill.closed
            and bill.currency == currency
            and getattr(bill, "distribution_status", "final") == "final"
            and (bill_ids is None or bill.id in bill_ids)
        ),
        key=_bill_order_key,
    )


def find_debt_bill_ids(
    repository,
    debtor_id: str,
    creditor_id: str,
    currency: str,
) -> list[int]:
    debtor_bill_ids = {
        bill.id
        for bill in repository.get_bills_v2_for_person(debtor_id)
    }
    creditor_bill_ids = {
        bill.id
        for bill in repository.get_bills_v2_for_person(creditor_id)
    }
    accessible_bill_ids = debtor_bill_ids & creditor_bill_ids
    balances, _ = compute_bill_balances(
        repository.db.bills_v2,
        repository.db.bill_payments_v2,
    )
    return [
        bill.id
        for bill in _ordered_open_bills(
            repository,
            currency,
            accessible_bill_ids,
        )
        if balances.get(bill.id, {}).get(debtor_id, {}).get(creditor_id, 0) > 0
    ]


def payment_bills_phrase(repository, bill_ids: list[int]) -> str:
    names = [
        bill.name
        for bill_id in bill_ids
        if (bill := repository.get_bill_v2(bill_id))
    ]
    if not names:
        return ""

    if len(names) == 1:
        return f" по счёту «{fmt.md_inline(names[0])}»"

    shown = ", ".join(f"«{fmt.md_inline(name)}»" for name in names[:3])
    if len(names) > 3:
        shown += f" и ещё {len(names) - 3}"

    return f" по счетам {shown}"


def settle_payment(repository, payment: BillPaymentV2) -> PaymentSettlement:
    other_payments = [
        other
        for other in repository.db.bill_payments_v2
        if other.id != payment.id
    ]
    balances, _ = compute_bill_balances(
        repository.db.bills_v2,
        other_payments,
    )
    scoped_bill_ids = set(payment.bill_ids) if payment.bill_ids else None
    bills_with_debt = [
        (
            bill.id,
            balances.get(bill.id, {})
            .get(payment.debtor, {})
            .get(payment.creditor, 0),
        )
        for bill in _ordered_open_bills(
            repository,
            payment.currency,
            scoped_bill_ids,
        )
    ]
    allocations, residual = distribute_payment_amount(
        bills_with_debt,
        payment.amount_minor,
    )

    if payment in repository.db.bill_payments_v2:
        repository.db.bill_payments_v2.remove(payment)

    settled_at = datetime.now()
    settled_payments = [
        BillPaymentV2(
            id=str(uuid4()),
            debtor=payment.debtor,
            creditor=payment.creditor,
            amount_minor=amount,
            currency=payment.currency,
            status=PaymentStatus.CONFIRMED,
            created_at=payment.created_at,
            settled_at=settled_at,
            initiated_chat_id=payment.initiated_chat_id,
            confirmation_chat_id=payment.confirmation_chat_id,
            confirmation_message_id=payment.confirmation_message_id,
            bill_ids=[bill_id],
            is_refund=getattr(payment, "is_refund", False),
        )
        for bill_id, amount in allocations
    ]
    if residual > 0:
        settled_payments.append(
            BillPaymentV2(
                id=str(uuid4()),
                debtor=payment.debtor,
                creditor=payment.creditor,
                amount_minor=residual,
                currency=payment.currency,
                status=PaymentStatus.CONFIRMED,
                created_at=payment.created_at,
                settled_at=settled_at,
                initiated_chat_id=payment.initiated_chat_id,
                confirmation_chat_id=payment.confirmation_chat_id,
                confirmation_message_id=payment.confirmation_message_id,
                bill_ids=[],
                is_refund=getattr(payment, "is_refund", False),
            )
        )

    repository.db.bill_payments_v2.extend(settled_payments)
    updated_balances, _ = compute_bill_balances(
        repository.db.bills_v2,
        repository.db.bill_payments_v2,
    )
    auto_closed = []
    for bill_id, _ in allocations:
        bill = repository.get_bill_v2(bill_id)
        if bill is None or bill.closed:
            continue

        balance = updated_balances.get(bill_id, {})
        if any(amount > 0 for creditors in balance.values() for amount in creditors.values()):
            continue

        bill.closed = True
        bill.closed_at = settled_at
        bill.updated_at = settled_at
        auto_closed.append(bill)

    return PaymentSettlement(
        allocations=allocations,
        residual_minor=residual,
        auto_closed=auto_closed,
        payments=settled_payments,
    )


def _confirmation_markup(payment_id: str):
    return Keyboard.row(
        _PAY_CONFIRM.button(
            "✅ Получил",
            payment_id=payment_id,
        ),
        _PAY_REJECT.button(
            "❌ Не получал",
            payment_id=payment_id,
        ),
    ).to_markup()


async def notify_payment_confirmed(
    bot,
    repository,
    payment: BillPaymentV2,
    creditor,
    settlement: PaymentSettlement,
) -> None:
    debtor = repository.get_bill_person(payment.debtor)
    if debtor is None or debtor.telegram_id is None:
        return

    debtor_mention = (
        f"[{fmt.md_inline(debtor.display_name)}]"
        f"(tg://user?id={debtor.telegram_id})"
    )
    amount = fmt.minor_to_display(payment.amount_minor, payment.currency)
    bill_ids = [bill_id for bill_id, _ in settlement.allocations]
    await send_bill_notification(
        bot,
        repository,
        debtor,
        f"✅ {debtor_mention}, {fmt.md_inline(creditor.display_name)} "
        f"подтвердил получение твоего перевода *{amount}*"
        f"{payment_bills_phrase(repository, bill_ids)}.",
        sender=creditor,
        parse_mode="Markdown",
        initiated_chat_id=payment.initiated_chat_id,
        prefer_dm=True,
    )


async def register_outgoing_payment(
    bot,
    repository,
    debtor,
    creditor,
    amount_minor: int,
    currency: str,
    initiated_chat_id: int | None,
    bill_ids: list[int] | None = None,
) -> tuple[BillPaymentV2, PaymentSettlement | None]:
    if amount_minor <= 0:
        raise ValueError("amount must be positive")

    available_bill_ids = find_debt_bill_ids(
        repository,
        debtor.id,
        creditor.id,
        currency,
    )
    if bill_ids:
        requested_bill_ids = set(bill_ids)
        payment_bill_ids = [
            bill_id
            for bill_id in available_bill_ids
            if bill_id in requested_bill_ids
        ]
    else:
        payment_bill_ids = available_bill_ids

    payment = BillPaymentV2(
        id=str(uuid4()),
        debtor=debtor.id,
        creditor=creditor.id,
        amount_minor=amount_minor,
        currency=currency,
        status=PaymentStatus.PENDING,
        initiated_chat_id=initiated_chat_id,
        bill_ids=payment_bill_ids,
    )
    repository.db.bill_payments_v2.append(payment)

    if creditor.telegram_id is None:
        payment.status = PaymentStatus.AUTO_CONFIRMED
        payment.settled_at = datetime.now()
        settlement = settle_payment(repository, payment)
        await repository.save()
        return payment, settlement

    schedule_payment_reminder(repository, payment.id)
    amount = fmt.minor_to_display(amount_minor, currency)
    creditor_mention = (
        f"[{fmt.md_inline(creditor.display_name)}]"
        f"(tg://user?id={creditor.telegram_id})"
    )
    notification = await send_bill_notification(
        bot,
        repository,
        creditor,
        f"💸 {fmt.md_inline(debtor.display_name)} говорит, что перевёл "
        f"{creditor_mention} *{amount}*"
        f"{payment_bills_phrase(repository, payment_bill_ids)}\nПодтверди получение:",
        sender=debtor,
        reply_markup=_confirmation_markup(payment.id),
        parse_mode="Markdown",
        initiated_chat_id=initiated_chat_id,
        prefer_dm=True,
    )
    if notification is not None:
        payment.confirmation_chat_id = notification.chat_id
        payment.confirmation_message_id = notification.message_id

    await repository.save()
    logger.info(
        "Payment %s created: %s -> %s %s, notified=%s",
        payment.id[:8],
        debtor.display_name,
        creditor.display_name,
        amount,
        bool(notification),
    )
    return payment, None


async def register_received_payment(
    bot,
    repository,
    creditor,
    debtor,
    amount_minor: int,
    currency: str,
    initiated_chat_id: int | None,
    bill_ids: list[int] | None = None,
) -> tuple[BillPaymentV2, PaymentSettlement]:
    if amount_minor <= 0:
        raise ValueError("amount must be positive")

    created_at = datetime.now()
    payment = BillPaymentV2(
        id=str(uuid4()),
        debtor=debtor.id,
        creditor=creditor.id,
        amount_minor=amount_minor,
        currency=currency,
        status=PaymentStatus.CONFIRMED,
        created_at=created_at,
        settled_at=created_at,
        initiated_chat_id=initiated_chat_id,
        bill_ids=[],
    )
    available_bill_ids = find_debt_bill_ids(
        repository,
        debtor.id,
        creditor.id,
        currency,
    )
    if bill_ids:
        requested_bill_ids = set(bill_ids)
        payment.bill_ids = [
            bill_id
            for bill_id in available_bill_ids
            if bill_id in requested_bill_ids
        ]
    else:
        payment.bill_ids = available_bill_ids

    repository.db.bill_payments_v2.append(payment)
    settlement = settle_payment(repository, payment)
    await notify_payment_confirmed(
        bot,
        repository,
        payment,
        creditor,
        settlement,
    )
    await repository.save()
    return payment, settlement
