import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from steward.api import server
from steward.data.models.bill_v2 import (
    BillItemAssignment,
    BillPaymentV2,
    BillPerson,
    BillTransaction,
    BillV2,
    PaymentStatus,
)
from steward.helpers.bills_history import build_debt_history
from steward.helpers.bills_money import compute_bill_balances
from tests.conftest import make_repository


def ts(day, hour=0, minute=0, microsecond=0):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc, microsecond=microsecond)


def make_bill(
    bill_id,
    debtor,
    creditor,
    amount_minor,
    created_at,
    *,
    currency="BYN",
    closed=False,
    closed_at=None,
    distribution_status="final",
    origin_chat_id=None,
    transactions=None,
):
    if transactions is None:
        transactions = [
            BillTransaction(
                id=f"tx-{bill_id}-1",
                item_name=f"Товар {bill_id}",
                creditor=creditor,
                unit_price_minor=amount_minor,
                assignments=[BillItemAssignment(1, [debtor])],
                created_at=created_at,
            )
        ]
    return BillV2(
        id=bill_id,
        name=f"Счёт {bill_id}",
        author_person_id=creditor,
        participants=[debtor, creditor],
        transactions=transactions,
        created_at=created_at,
        closed=closed,
        closed_at=closed_at,
        currency=currency,
        distribution_status=distribution_status,
        origin_chat_id=origin_chat_id,
    )


def make_payment(
    payment_id,
    debtor,
    creditor,
    amount_minor,
    created_at,
    *,
    settled_at=None,
    status=PaymentStatus.CONFIRMED,
    bill_ids=(),
    currency="BYN",
    is_refund=False,
):
    return BillPaymentV2(
        id=payment_id,
        debtor=debtor,
        creditor=creditor,
        amount_minor=amount_minor,
        status=status,
        created_at=created_at,
        settled_at=settled_at,
        bill_ids=list(bill_ids),
        currency=currency,
        is_refund=is_refund,
    )


def find_event(history, event_type, debtor="d", creditor="c", currency="BYN"):
    return next(
        item
        for item in history["events"]
        if item["type"] == event_type
        and item["debtor"] == debtor
        and item["creditor"] == creditor
        and item["currency"] == currency
    )


def transition(item, before, delta, after):
    assert (item["before_minor"], item["delta_minor"], item["after_minor"]) == (
        before,
        delta,
        after,
    )


def history_balances(history):
    return {
        (item["debtor"], item["creditor"], item["currency"], item["amount_minor"])
        for item in history["balances"]
    }


def test_final_charges_group_settled_split_payments_and_skip_draft_pending_rejected():
    bill = make_bill(1, "d", "c", 1000, ts(1))
    bill.transactions[0].source = "sheet"
    bill.transactions[0].created_at = ts(2)
    draft = make_bill(2, "d", "c", 900, ts(1, 1), distribution_status="draft")
    created = datetime(2026, 1, 2, 9)
    payments = [
        make_payment("p1", "d", "c", 300, created, settled_at=ts(3, 12), bill_ids=[1]),
        make_payment("p2", "d", "c", 200, created, settled_at=ts(3, 12), bill_ids=[1]),
        make_payment("pending", "d", "c", 100, ts(4), settled_at=ts(4, 1), status=PaymentStatus.PENDING),
        make_payment("rejected", "d", "c", 100, ts(4, 2), settled_at=ts(4, 3), status=PaymentStatus.REJECTED),
    ]

    history = build_debt_history([bill, draft], payments, "d")

    assert [item["type"] for item in history["events"]] == ["payment", "charge"]
    charge = find_event(history, "charge")
    payment = find_event(history, "payment")
    assert charge["amount_minor"] == 1000
    assert charge["bills"][0]["id"] == 1
    assert charge["items"] == [{"name": "Товар 1", "amount_minor": 1000}]
    transition(charge, 0, 1000, 1000)
    assert payment["amount_minor"] == 500
    assert payment["date"] == ts(3, 12).isoformat()
    transition(payment, 1000, -500, 500)
    assert [item["id"] for item in payment["bills"]] == [1]


def test_history_orders_mixed_timezone_instants_and_uses_settled_date():
    created = datetime(2026, 1, 1, 12)
    bill = make_bill(1, "d", "c", 1000, created)
    payment = make_payment(
        "p1",
        "d",
        "c",
        100,
        datetime(2026, 1, 1, 12, 30),
        settled_at=datetime(2026, 1, 1, 13, tzinfo=timezone.utc),
        bill_ids=[1],
    )

    history = build_debt_history([bill], [payment], "d")

    assert [item["type"] for item in history["events"]] == ["payment", "charge"]
    assert find_event(history, "payment")["date"] == "2026-01-01T13:00:00+00:00"


def test_initial_bill_items_share_one_charge_with_subtotals_and_period():
    transactions = [
        BillTransaction(
            id="tx-1",
            item_name="Ужин",
            creditor="c",
            unit_price_minor=1000,
            assignments=[BillItemAssignment(1, ["d"])],
            created_at=ts(1),
        ),
        BillTransaction(
            id="tx-2",
            item_name="Ужин",
            creditor="c",
            unit_price_minor=500,
            assignments=[BillItemAssignment(1, ["d"])],
            created_at=ts(1, microsecond=123),
        ),
        BillTransaction(
            id="tx-3",
            item_name="Такси",
            creditor="c",
            unit_price_minor=200,
            assignments=[BillItemAssignment(1, ["d"])],
            created_at=ts(2),
        ),
    ]
    bill = make_bill(1, "d", "c", 0, ts(1), transactions=transactions)

    history = build_debt_history([bill], [], "d")

    charges = [item for item in history["events"] if item["type"] == "charge"]
    assert len(charges) == 1
    charge = charges[0]
    assert charge["date"] == ts(1).isoformat()
    assert charge["date_to"] == ts(2).isoformat()
    assert charge["items"] == [
        {"name": "Ужин", "amount_minor": 1500},
        {"name": "Такси", "amount_minor": 200},
    ]
    transition(charge, 0, 1700, 1700)


def test_other_bill_same_pair_breaks_charge_group():
    first_transactions = [
        BillTransaction(
            id="a-1",
            item_name="A первый",
            creditor="c",
            unit_price_minor=100,
            assignments=[BillItemAssignment(1, ["d"])],
            created_at=ts(1),
        ),
        BillTransaction(
            id="a-2",
            item_name="A второй",
            creditor="c",
            unit_price_minor=300,
            assignments=[BillItemAssignment(1, ["d"])],
            created_at=ts(3),
        ),
    ]
    first = make_bill(1, "d", "c", 0, ts(1), transactions=first_transactions)
    second = make_bill(2, "d", "c", 200, ts(2))

    history = build_debt_history([first, second], [], "d")

    charges = [item for item in history["events"] if item["type"] == "charge"]
    assert len(charges) == 3
    first_charge = next(item for item in charges if item["date"] == ts(1).isoformat())
    second_charge = next(item for item in charges if item["date"] == ts(2).isoformat())
    last_charge = next(item for item in charges if item["date"] == ts(3).isoformat())
    transition(first_charge, 0, 100, 100)
    transition(second_charge, 100, 200, 300)
    transition(last_charge, 300, 300, 600)
    assert history_balances(history) == {("d", "c", "BYN", 600)}


def test_new_expense_in_same_bill_is_added_after_an_intermediate_payment():
    transactions = [
        BillTransaction(
            id="tx-1",
            item_name="Первый товар",
            creditor="c",
            unit_price_minor=1000,
            assignments=[BillItemAssignment(1, ["d"])],
            created_at=ts(1),
        ),
        BillTransaction(
            id="tx-2",
            item_name="Второй товар",
            creditor="c",
            unit_price_minor=500,
            assignments=[BillItemAssignment(1, ["d"])],
            created_at=ts(3),
        ),
    ]
    bill = make_bill(1, "d", "c", 0, ts(1), transactions=transactions)
    payment = make_payment("p1", "d", "c", 500, ts(2), settled_at=ts(2, 1), bill_ids=[1])

    history = build_debt_history([bill], [payment], "d")
    charges = [item for item in history["events"] if item["type"] == "charge"]
    first = next(item for item in charges if item["date"] == ts(1).isoformat())
    second = next(item for item in charges if item["date"] == ts(3).isoformat())

    assert len(charges) == 2
    transition(first, 0, 1000, 1000)
    transition(second, 500, 500, 1000)
    assert find_event(history, "payment")["after_minor"] == 500


def test_manual_close_is_cancellation_and_auto_close_has_no_extra_event():
    manual = make_bill(1, "d", "c", 1000, ts(1), closed=True, closed_at=ts(4))
    partial = make_payment("partial", "d", "c", 200, ts(2), settled_at=ts(2, 1), bill_ids=[1])
    history = build_debt_history([manual], [partial], "d")
    close = find_event(history, "close")
    assert close["amount_minor"] == 0
    transition(close, 800, -800, 0)
    transition(find_event(history, "payment"), 1000, -200, 800)

    auto = make_bill(2, "d", "c", 1000, ts(5), closed=True, closed_at=ts(6))
    settled = make_payment("settled", "d", "c", 1000, ts(5, 1), settled_at=ts(6), bill_ids=[2])
    auto_history = build_debt_history([auto], [settled], "d")
    assert [item["type"] for item in auto_history["events"]] == ["payment", "charge"]
    assert find_event(auto_history, "payment")["after_minor"] == 0


def test_overpayment_is_carried_to_a_later_bill_and_matches_current_balance():
    first = make_bill(1, "d", "c", 1000, ts(1), closed=True, closed_at=ts(2))
    second = make_bill(2, "d", "c", 500, ts(3))
    payments = [
        make_payment("allocated", "d", "c", 1000, ts(1, 1), settled_at=ts(2), bill_ids=[1]),
        make_payment("credit", "d", "c", 200, ts(1, 1), settled_at=ts(2)),
    ]

    history = build_debt_history([first, second], payments, "d")
    payment = find_event(history, "payment")
    second_charge = next(item for item in history["events"] if item["type"] == "charge" and item["bills"][0]["id"] == 2)
    assert payment["amount_minor"] == 1200
    transition(payment, 1000, -1200, -200)
    transition(second_charge, -200, 500, 300)
    balances, credits = compute_bill_balances([first, second], payments)
    assert credits == {}
    assert history_balances(history) == {("d", "c", "BYN", 300)}
    assert balances[1] == {}
    assert balances[2]["d"]["c"] == 300


def test_refund_increases_debt_and_writeoff_reduces_credit():
    bill = make_bill(1, "d", "c", 1000, ts(1))
    refund = make_payment("refund", "c", "d", 200, ts(2), settled_at=ts(2, 1), bill_ids=[1], is_refund=True)
    history = build_debt_history([bill], [refund], "d")
    assert len(history["events"]) == 2
    adjustment = find_event(history, "adjustment")
    assert adjustment["amount_minor"] == 200
    transition(adjustment, 1000, 200, 1200)
    assert not any(item["debtor"] == "c" and item["creditor"] == "d" for item in history["events"])

    credit = make_payment("credit", "d", "c", 300, ts(3), settled_at=ts(3, 1))
    writeoff = make_payment("writeoff", "d", "c", 100, ts(4), settled_at=ts(4, 1), is_refund=True)
    history = build_debt_history([], [credit, writeoff], "d")
    transition(find_event(history, "payment"), 0, -300, -300)
    transition(find_event(history, "adjustment"), -300, 100, -200)


def test_reciprocal_pairs_and_currencies_have_independent_running_balances():
    bills = [
        make_bill(1, "d", "c", 1000, ts(1), currency="BYN"),
        make_bill(2, "c", "d", 300, ts(2), currency="BYN"),
        make_bill(3, "d", "c", 500, ts(3), currency="USD"),
    ]
    payments = [
        make_payment("byn", "d", "c", 100, ts(4), settled_at=ts(4, 1), bill_ids=[1]),
        make_payment("usd", "d", "c", 200, ts(5), settled_at=ts(5, 1), bill_ids=[3], currency="USD"),
    ]

    history = build_debt_history(bills, payments, "d")

    assert history_balances(history) == {
        ("d", "c", "BYN", 900),
        ("c", "d", "BYN", 300),
        ("d", "c", "USD", 300),
    }
    assert {(
        item["debtor"], item["creditor"], item["currency"]
    ) for item in history["events"]} == {
        ("d", "c", "BYN"),
        ("c", "d", "BYN"),
        ("d", "c", "USD"),
    }


def test_legacy_closed_bill_without_close_date_marks_rows_unknown():
    bill = make_bill(1, "d", "c", 1000, ts(1), closed=True)
    history = build_debt_history([bill], [], "d")

    assert len(history["events"]) == 2
    charge = find_event(history, "charge")
    close = find_event(history, "close")
    assert charge["date"] == ts(1).isoformat()
    assert close["date"] is None
    assert not charge["balance_known"] and not close["balance_known"]
    transition(charge, 0, 0, 0)
    transition(close, 0, 0, 0)


def make_request(repository):
    request = MagicMock()
    request.app = {"repository": repository}
    request.match_info = {}
    request.json = AsyncMock(return_value={})
    return request


async def test_history_endpoint_returns_callers_pairs_from_all_chats_only(monkeypatch):
    repository = make_repository()
    repository.db.bill_persons.extend([
        BillPerson(id="d", display_name="Дима", telegram_id=101),
        BillPerson(id="c", display_name="Кирилл", telegram_id=202),
        BillPerson(id="x", display_name="Икс", telegram_id=303),
        BillPerson(id="y", display_name="Игрек", telegram_id=404),
    ])
    repository.db.bills_v2.extend([
        make_bill(1, "d", "c", 100, ts(1), origin_chat_id=-101),
        make_bill(2, "d", "c", 200, ts(2), origin_chat_id=-202),
        make_bill(3, "x", "y", 300, ts(3), origin_chat_id=-303),
    ])
    repository.db.bill_payments_v2.extend([
        make_payment("p1", "d", "c", 50, ts(4), settled_at=ts(4, 1), bill_ids=[1]),
        make_payment("p2", "x", "y", 50, ts(4), settled_at=ts(4, 1), bill_ids=[3]),
    ])
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda _: {"id": 101})

    response = await server.handle_bills_history(make_request(repository))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["person_id"] == "d"
    assert {item["id"] for item in payload["persons"]} == {"d", "c"}
    assert {item["bills"][0]["id"] for item in payload["events"]} == {1, 2}
    assert not any(item["debtor"] in {"x", "y"} or item["creditor"] in {"x", "y"} for item in payload["events"])

    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda _: None)
    response = await server.handle_bills_history(make_request(repository))
    assert response.status == 401
