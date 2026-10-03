from unittest.mock import AsyncMock, MagicMock

import pytest

from steward.api import server
from steward.data.models.bill_v2 import (
    BillItemAssignment,
    BillPerson,
    BillTransaction,
    BillV2,
)
from steward.helpers.bills_validation import (
    is_distribution_incomplete,
    parse_assignment_list,
    validate_transaction_values,
)
from tests.conftest import make_repository


def make_bill(*transactions, status="distributing"):
    return BillV2(
        id=1,
        name="Ужин",
        author_person_id="author",
        participants=["author", "friend"],
        transactions=list(transactions),
        distribution_status=status,
    )


def make_transaction(*, quantity=1, assignments=None):
    return BillTransaction(
        id="tx",
        item_name="Позиция",
        creditor="author",
        unit_price_minor=100,
        quantity=quantity,
        assignments=assignments or [],
    )


def make_request(repository, data=None, bill_id=1, tx_id=None):
    request = MagicMock()
    request.app = {"repository": repository, "bot": MagicMock()}
    request.match_info = {"id": str(bill_id)}
    if tx_id is not None:
        request.match_info["tid"] = tx_id
    request.json = AsyncMock(return_value=data)
    return request


def test_validation_allows_partial_and_empty_assignments():
    assignments, error = parse_assignment_list(
        [
            {"unit_count": 1, "denominator": 2, "debtors": ["author", "friend"]},
            {"unit_count": 1, "denominator": 2, "debtors": []},
        ],
        label="позиция «Кальян»",
    )

    assert error is None
    assert validate_transaction_values(850, 1, assignments) is None


def test_validation_allows_quantity_two_shared_between_people():
    assignments = [
        BillItemAssignment(unit_count=2, debtors=["author", "friend"]),
    ]

    assert validate_transaction_values(850, 2, assignments) is None


def test_distribution_incomplete_tracks_coverage_and_unknown_debtors():
    assert is_distribution_incomplete(
        [BillItemAssignment(unit_count=1, debtors=["author"])],
        2,
    )
    assert not is_distribution_incomplete(
        [BillItemAssignment(unit_count=2, debtors=["author", "friend"])],
        2,
    )
    assert is_distribution_incomplete(
        [BillItemAssignment(unit_count=2, debtors=["__unknown__"])],
        2,
    )


@pytest.mark.parametrize(
    ("price", "quantity", "assignments", "needle"),
    [
        (-1, 1, [], "цена"),
        (100, 0, [], "количество"),
        (100, 1, [BillItemAssignment(0, [])], "количество"),
        (100, 1, [BillItemAssignment(1, [], 0)], "знаменатель"),
        (100, 1, [BillItemAssignment(1, ["author", "author"])], "несколько раз"),
        (100, 1, [BillItemAssignment(1, ["author"]), BillItemAssignment(1, [])], "распределено"),
    ],
)
def test_validation_rejects_invalid_values(price, quantity, assignments, needle):
    error = validate_transaction_values(price, quantity, assignments, label="позиция «Пицца»")

    assert error is not None
    assert needle in error


def test_parse_assignment_rejects_duplicate_debtors():
    assignments, error = parse_assignment_list(
        [{"unit_count": 1, "debtors": ["author", "author"]}],
        label="позиция «Пицца»",
    )

    assert assignments is None
    assert "несколько раз" in error


async def test_tx_add_rejects_overassignment_without_mutation(monkeypatch):
    repository = make_repository()
    bill = make_bill()
    repository.db.bills_v2.append(bill)
    repository.db.bill_persons.append(
        BillPerson(id="author", display_name="Автор", telegram_id=1)
    )
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda _: {"id": 1})

    response = await server.handle_bills_tx_add(
        make_request(
            repository,
            {
                "item_name": "Пицца",
                "unit_price_minor": 100,
                "quantity": 1,
                "creditor": "author",
                "assignments": [
                    {"unit_count": 1, "debtors": ["author"]},
                    {"unit_count": 1, "debtors": []},
                ],
            },
        )
    )

    assert response.status == 400
    assert bill.transactions == []


async def test_tx_update_rejects_invalid_assignment_without_mutation(monkeypatch):
    repository = make_repository()
    tx = make_transaction(
        quantity=2,
        assignments=[BillItemAssignment(unit_count=1, debtors=["friend"])],
    )
    bill = make_bill(tx)
    repository.db.bills_v2.append(bill)
    repository.db.bill_persons.append(
        BillPerson(id="author", display_name="Автор", telegram_id=1)
    )
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda _: {"id": 1})

    response = await server.handle_bills_tx_update(
        make_request(
            repository,
            {"quantity": 1, "assignments": [{"unit_count": 2, "debtors": ["friend"]}]},
            tx_id=tx.id,
        )
    )

    assert response.status == 400
    assert tx.quantity == 2
    assert tx.assignments == [BillItemAssignment(unit_count=1, debtors=["friend"])]


async def test_distribution_validates_all_positions_before_mutation(monkeypatch):
    repository = make_repository()
    first = make_transaction()
    second = BillTransaction(
        id="tx-2",
        item_name="Вторая позиция",
        creditor="author",
        unit_price_minor=100,
        quantity=1,
        assignments=[BillItemAssignment(unit_count=1, debtors=[])],
    )
    bill = make_bill(first, second, status="final")
    repository.db.bills_v2.append(bill)
    repository.db.bill_persons.append(
        BillPerson(id="author", display_name="Автор", telegram_id=1)
    )
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda _: {"id": 1})

    response = await server.handle_bills_distribute(
        make_request(
            repository,
            {
                "transactions": [
                    {"id": first.id, "assignments": [{"unit_count": 1, "debtors": ["friend"]}]},
                    {
                        "id": second.id,
                        "assignments": [
                            {"unit_count": 1, "debtors": []},
                            {"unit_count": 1, "debtors": ["friend"]},
                        ],
                    },
                ]
            },
        )
    )

    assert response.status == 400
    assert first.assignments == []
    assert second.assignments == [BillItemAssignment(unit_count=1, debtors=[])]
    assert bill.distribution_status == "final"


async def test_finalize_rejects_overassigned_position(monkeypatch):
    repository = make_repository()
    tx = make_transaction(
        assignments=[
            BillItemAssignment(unit_count=1, debtors=["friend"]),
            BillItemAssignment(unit_count=1, debtors=[]),
        ]
    )
    bill = make_bill(tx, status="distributing")
    repository.db.bills_v2.append(bill)
    repository.db.bill_persons.append(
        BillPerson(id="author", display_name="Автор", telegram_id=1)
    )
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda _: {"id": 1})

    response = await server.handle_bills_finalize(make_request(repository))

    assert response.status == 400
    assert bill.distribution_status == "distributing"
