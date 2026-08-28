from datetime import datetime, timedelta

from steward.data.models.bill_v2 import (
    BillItemAssignment,
    BillPaymentV2,
    BillPerson,
    BillTransaction,
    BillV2,
)
from steward.features.bills import fmt


def make_people():
    return {
        "kirill": BillPerson(
            id="kirill",
            display_name="Кирилл",
        ),
        "dmitrux": BillPerson(
            id="dmitrux",
            display_name="Дима",
        ),
    }


def make_closed_bill_and_payments():
    closed_at = datetime(2026, 8, 28, 11, 28)
    bill = BillV2(
        id=43,
        name="Драккар",
        author_person_id="kirill",
        participants=["kirill", "dmitrux"],
        transactions=[
            BillTransaction(
                id="tx-43",
                item_name="Игры",
                creditor="kirill",
                unit_price_minor=3200,
                assignments=[
                    BillItemAssignment(
                        unit_count=1,
                        debtors=["dmitrux"],
                    )
                ],
            )
        ],
        closed=True,
        closed_at=closed_at,
    )
    overpayment = BillPaymentV2(
        id="overpayment",
        debtor="dmitrux",
        creditor="kirill",
        amount_minor=2360,
        status="confirmed",
        bill_ids=[],
        created_at=closed_at - timedelta(days=14),
    )
    transfer = BillPaymentV2(
        id="transfer",
        debtor="dmitrux",
        creditor="kirill",
        amount_minor=840,
        status="confirmed",
        bill_ids=[43],
        created_at=closed_at - timedelta(microseconds=1),
    )
    return bill, [overpayment, transfer]


def test_closed_bill_plain_detail_shows_credit_usage():
    bill, payments = make_closed_bill_and_payments()

    text = fmt.format_bill_detail(
        bill,
        "kirill",
        make_people(),
        payments,
        [bill],
    )

    assert "Из переплаты оплачено: 23.60 р" in text
    assert "Кто кому" not in text


def test_closed_bill_rich_detail_shows_credit_usage():
    bill, payments = make_closed_bill_and_payments()

    text = fmt.format_bill_detail_rich(
        bill,
        "kirill",
        make_people(),
        payments,
        [bill],
    )

    assert "Из переплаты оплачено:** 23.60 р" in text
    assert "Кто кому" not in text


def test_created_bill_shows_credit_usage():
    bill, payments = make_closed_bill_and_payments()
    bill.closed = False
    bill.closed_at = None

    text = fmt.format_bill_created(
        bill,
        make_people(),
        payments,
        [bill],
    )

    assert "Из переплаты оплачено: 23.60 р" in text


def test_overview_shows_credit_without_bills():
    _, payments = make_closed_bill_and_payments()

    text = fmt.format_overview(
        [],
        "dmitrux",
        make_people(),
        [payments[0]],
    )

    assert "Твои переплаты" in text
    assert "23.60 р" in text


def test_closed_bill_serializer_keeps_credit_usage_and_debts():
    from steward.api.server import _serialize_bill_v2

    bill, payments = make_closed_bill_and_payments()

    payload = _serialize_bill_v2(
        bill,
        payments,
        {},
        2360,
    )

    assert payload["closed"] is True
    assert payload["debts"] == {}
    assert payload["applied_credit_minor"] == 2360
