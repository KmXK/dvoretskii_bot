import json
from dataclasses import asdict
from unittest.mock import MagicMock

import pytest

from steward.api import server
from steward.data.models.bill_v2 import BillPerson, PaymentStatus
from steward.features.bills.payments import find_debt_bill_ids, settle_debt_offsets, settle_payment
from steward.helpers.bills_history import build_debt_history
from steward.helpers.bills_money import compute_bill_balance_details, compute_bill_balances
from steward.data.models.db import parse_from_dict
from tests.conftest import make_repository
from tests.test_bills_history import make_bill, make_payment, ts


@pytest.mark.parametrize("debtor,creditor", [("me", "alex"), ("alex", "me")])
def test_confirmed_payment_leaves_eight_kopecks_after_mutual_offset(debtor, creditor):
    bills = [
        make_bill(63, creditor, debtor, 4508, ts(1)),
        make_bill(64, debtor, creditor, 6900, ts(2)),
    ]
    payment = make_payment("24", debtor, creditor, 2400, ts(3), bill_ids=[64])
    applied = {}

    balances, credits, _ = compute_bill_balance_details(bills, [payment], applied_offsets=applied)

    assert balances == {63: {creditor: {debtor: 8}}, 64: {}}
    assert credits == {}
    assert applied == {63: 4500, 64: 4500}
    assert bills[0].transactions[0].unit_price_minor == 4508


@pytest.mark.parametrize("status", [PaymentStatus.PENDING, PaymentStatus.REJECTED])
def test_unconfirmed_payment_does_not_reduce_debt(status):
    bills = [make_bill(1, "a", "b", 6900, ts(1)), make_bill(2, "b", "a", 4508, ts(2))]
    payment = make_payment("p", "a", "b", 2400, ts(3), bill_ids=[1], status=status)

    balances, credits = compute_bill_balances(bills, [payment])

    assert balances == {1: {"a": {"b": 2392}}, 2: {}}
    assert credits == {}


def test_offsets_are_fifo_and_do_not_cross_currencies_people_or_closed_draft_bills():
    bills = [
        make_bill(1, "a", "b", 1000, ts(1)),
        make_bill(2, "a", "b", 1000, ts(2)),
        make_bill(3, "b", "a", 1500, ts(3)),
        make_bill(4, "b", "a", 700, ts(1), currency="USD"),
        make_bill(5, "b", "a", 700, ts(1), distribution_status="draft"),
        make_bill(6, "b", "a", 700, ts(1), closed=True, closed_at=ts(2)),
        make_bill(7, "b", "c", 700, ts(1)),
        make_bill(8, "c", "a", 700, ts(1)),
    ]

    balances, _ = compute_bill_balances(list(reversed(bills)), [])

    assert balances == {
        1: {}, 2: {"a": {"b": 500}}, 3: {}, 4: {"b": {"a": 700}},
        5: {}, 6: {}, 7: {"b": {"c": 700}}, 8: {"c": {"a": 700}},
    }


def test_settlement_freezes_offsets_and_closing_does_not_restore_opposite_debt():
    repository = make_repository()
    first = make_bill(1, "a", "b", 4508, ts(1))
    second = make_bill(2, "b", "a", 4500, ts(2))
    repository.db.bills_v2 = [first, second]
    payment = make_payment("p", "a", "b", 8, ts(3), bill_ids=[1])
    repository.db.bill_payments_v2.append(payment)

    settlement = settle_payment(repository, payment)

    assert settlement.allocations == [(1, 8)]
    assert settlement.residual_minor == 0
    assert first.closed
    assert not second.closed
    assert compute_bill_balances(repository.db.bills_v2, repository.db.bill_payments_v2) == ({1: {}, 2: {}}, {})
    assert settle_debt_offsets(repository) == []
    offsets = [p for p in repository.db.bill_payments_v2 if p.status == PaymentStatus.OFFSET]
    assert sorted((p.bill_ids, p.amount_minor) for p in offsets) == [([1], 4500), ([2], 4500)]

    first.closed = False
    first.closed_at = None
    assert compute_bill_balances(repository.db.bills_v2, repository.db.bill_payments_v2) == ({1: {}, 2: {}}, {})
    restored = parse_from_dict(json.loads(json.dumps({
        "bills_v2": [asdict(b) for b in repository.db.bills_v2],
        "bill_payments_v2": [asdict(p) for p in repository.db.bill_payments_v2],
    }, default=str)))
    assert compute_bill_balances(restored.bills_v2, restored.bill_payments_v2) == ({1: {}, 2: {}}, {})


def test_overpayment_and_existing_credit_survive_offset_settlement():
    repository = make_repository()
    repository.db.bills_v2 = [
        make_bill(1, "a", "b", 1000, ts(1)),
        make_bill(2, "a", "b", 1000, ts(2)),
        make_bill(3, "b", "a", 500, ts(3)),
    ]
    repository.db.bill_payments_v2 = [make_payment("credit", "a", "b", 1200, ts(4))]
    payment = make_payment("cash", "a", "b", 400, ts(5))

    settlement = settle_payment(repository, payment)

    assert settlement.allocations == [(2, 300)]
    assert settlement.residual_minor == 100
    assert compute_bill_balances(repository.db.bills_v2, repository.db.bill_payments_v2) == (
        {1: {}, 2: {}, 3: {}}, {("a", "b", "BYN"): 100},
    )


def test_history_and_payment_choices_use_the_same_net_balance():
    repository = make_repository()
    repository.db.bills_v2 = [make_bill(1, "a", "b", 4508, ts(1)), make_bill(2, "b", "a", 4500, ts(2))]

    assert find_debt_bill_ids(repository, "a", "b", "BYN") == [1]
    assert find_debt_bill_ids(repository, "b", "a", "BYN") == []
    history = build_debt_history(repository.db.bills_v2, [], "a")
    assert history["balances"] == [{"debtor": "a", "creditor": "b", "currency": "BYN", "amount_minor": 8}]

    payment = make_payment("p", "a", "b", 8, ts(3))
    settle_payment(repository, payment)
    history = build_debt_history(repository.db.bills_v2, repository.db.bill_payments_v2, "a")
    assert history["balances"] == []
    assert sum(e["amount_minor"] for e in history["events"] if e["type"] == "payment") == 8
    assert not [e for e in history["events"] if e["type"] == "offset"]


def test_auto_close_preserves_offsets_for_other_people_in_same_bill():
    repository = make_repository()
    first = make_bill(1, "a", "b", 8, ts(1))
    first.transactions.extend(make_bill(10, "c", "d", 100, ts(1)).transactions)
    repository.db.bills_v2 = [first, make_bill(2, "d", "c", 100, ts(2))]

    settle_payment(repository, make_payment("cash", "a", "b", 8, ts(3)))

    assert first.closed
    assert compute_bill_balances(repository.db.bills_v2, repository.db.bill_payments_v2) == ({1: {}, 2: {}}, {})
    history = build_debt_history(repository.db.bills_v2, repository.db.bill_payments_v2, "c")
    assert history["balances"] == []
    assert not [e for e in history["events"] if e["type"] in ("offset", "close")]


async def test_api_displays_offsets_and_keeps_them_when_bill_is_closed(monkeypatch):
    repository = make_repository()
    repository.db.bill_persons = [BillPerson(id="a", display_name="A", telegram_id=101), BillPerson(id="b", display_name="B", telegram_id=202)]
    repository.db.bills_v2 = [make_bill(1, "a", "b", 4508, ts(1)), make_bill(2, "b", "a", 4500, ts(2))]
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda request: {"id": 101})
    request = MagicMock()
    request.app = {"repository": repository}
    request.match_info = {"id": "2"}
    request.query = {}

    payload = json.loads((await server.handle_bills_list(request)).text)
    assert {b["id"]: b["debts"] for b in payload["bills"]} == {1: {"a": {"b": 8}}, 2: {}}
    assert all(b["applied_offset_minor"] == 4500 for b in payload["bills"])
    assert (await server.handle_bills_close(request)).status == 200
    assert compute_bill_balances(repository.db.bills_v2, repository.db.bill_payments_v2) == ({1: {"a": {"b": 8}}, 2: {}}, {})
    payload = json.loads((await server.handle_bills_get(request)).text)
    assert payload["applied_offset_minor"] == 4500
    assert payload["payments"][0]["status"] == "offset"
    assert payload["transactions"][0]["locked"]
