import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from steward.api import bill_activity as activity_api
from steward.api import server
from steward.data.models.bill_v2 import BillItemAssignment, BillPerson, BillTransaction, BillV2
from steward.data.models.db import parse_from_dict, serialize_to_dict
from steward.data.models.user import User
from steward.data.repository import JsonEncoder
from steward.helpers.bill_activity import bill_activity_actor
from tests.conftest import make_repository


def make_activity_repository():
    repository = make_repository()
    repository.db.bill_persons = [
        BillPerson(id="me", display_name="Кирилл", telegram_id=101),
        BillPerson(id="dima", display_name="Дима", telegram_id=202),
    ]
    repository.db.bills_v2 = [BillV2(
        id=7,
        name="Ужин",
        author_person_id="me",
        participants=["me", "dima"],
        transactions=[BillTransaction(
            id="ice",
            item_name="Мороженое",
            creditor="me",
            unit_price_minor=850,
            quantity=2,
            assignments=[BillItemAssignment(1, ["me"]), BillItemAssignment(1, ["dima"])],
        )],
    )]
    return repository


async def test_activity_records_changes_and_keeps_deleted_item_details():
    repository = make_activity_repository()
    token = bill_activity_actor.set(101)
    try:
        await repository.save()
        assert len(repository.db.bill_activity) == 1
        assert [change.kind for change in repository.db.bill_activity[0].changes] == ["created", "item_added"]

        bill = repository.db.bills_v2[0]
        bill.updated_at = datetime.now(timezone.utc)
        await repository.save()
        assert len(repository.db.bill_activity) == 1

        bill.transactions[0].unit_price_minor = 900
        await repository.save()
        updated = repository.db.bill_activity[-1]
        assert updated.actor_telegram_id == 101
        assert updated.changes[0].fields == ["unit_price_minor"]
        assert updated.changes[0].before["unit_price_minor"] == 850
        assert updated.changes[0].after["unit_price_minor"] == 900

        bill.transactions.clear()
        await repository.save()
        removed = repository.db.bill_activity[-1].changes[0]
        assert removed.kind == "item_removed"
        assert removed.before["item_name"] == "Мороженое"
        assert removed.before["quantity"] == 2
        assert removed.after is None
    finally:
        bill_activity_actor.reset(token)


async def test_activity_survives_database_roundtrip():
    repository = make_activity_repository()
    await repository.save()

    encoded = json.dumps(serialize_to_dict(repository.db), cls=JsonEncoder)
    restored = parse_from_dict(json.loads(encoded))

    assert restored.bill_activity[0].bill_id == 7
    assert restored.bill_activity[0].created_at.tzinfo is not None
    assert restored.bill_activity[0].changes[1].after["quantity"] == 2


async def test_loading_existing_database_does_not_invent_history():
    repository = make_activity_repository()
    old_database = json.loads(json.dumps(serialize_to_dict(repository.db), cls=JsonEncoder))
    old_database.pop("bill_activity")

    async def read_database():
        return old_database

    repository._storage.read_dict = read_database
    await repository.migrate()

    assert repository.db.bill_activity == []
    repository.db.bills_v2[0].transactions[0].quantity = 3
    await repository.save()
    assert len(repository.db.bill_activity) == 1
    assert repository.db.bill_activity[0].changes[0].before["quantity"] == 2


async def test_failed_storage_write_does_not_leave_duplicate_activity():
    repository = make_activity_repository()
    original_write = repository._storage.write_dict

    async def fail_write(_):
        raise OSError("write failed")

    repository._storage.write_dict = fail_write
    with pytest.raises(OSError):
        await repository.save()

    assert repository.db.bill_activity == []
    repository._storage.write_dict = original_write
    await repository.save()
    assert len(repository.db.bill_activity) == 1


@pytest.mark.parametrize("user_id,status", [(101, 200), (202, 200), (303, 403), (None, 401)])
async def test_activity_endpoint_keeps_bill_access_rules(monkeypatch, user_id, status):
    repository = make_activity_repository()
    await repository.save()
    request = MagicMock()
    request.app = {"repository": repository}
    request.match_info = {"id": "7"}
    request.query = {}
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda _: {"id": user_id} if user_id else None)

    response = await server.handle_bill_activity(request)

    assert response.status == status
    if status == 200:
        payload = json.loads(response.text)
        assert payload["events"][0]["changes"][1]["after"]["item_name"] == "Мороженое"


async def test_actor_middleware_records_and_resets_author(monkeypatch):
    repository = make_activity_repository()
    request = MagicMock()
    monkeypatch.setattr(activity_api, "session_user_id", lambda _: 101)

    async def handler(_):
        await repository.save()
        return "ok"

    assert await activity_api.activity_actor_middleware(request, handler) == "ok"
    assert repository.db.bill_activity[0].actor_telegram_id == 101
    assert bill_activity_actor.get() is None


async def test_system_activity_is_not_attributed_to_an_anonymous_guest():
    repository = make_activity_repository()
    repository.db.bill_persons.insert(0, BillPerson(id="guest", display_name="Гость"))
    await repository.save()

    payload = activity_api.serialize_bill_activity(repository.db.bill_activity[0], repository)

    assert payload["actor"] is None


async def test_author_without_username_uses_first_name():
    repository = make_activity_repository()
    repository.db.users.append(User(id=303, first_name="Лёша"))
    token = bill_activity_actor.set(303)
    try:
        await repository.save()
    finally:
        bill_activity_actor.reset(token)

    payload = activity_api.serialize_bill_activity(repository.db.bill_activity[0], repository)

    assert payload["actor"] == "Лёша"


async def test_deleted_bill_id_is_not_reused_with_its_private_history():
    repository = make_activity_repository()
    await repository.save()
    repository.db.bills_v2.clear()
    await repository.save()

    assert repository.get_next_bill_v2_id() == 8


async def test_removed_item_keeps_original_currency_after_receipt_reparse():
    repository = make_activity_repository()
    await repository.save()
    bill = repository.db.bills_v2[0]
    bill.currency = "USD"
    bill.transactions.clear()
    await repository.save()

    removed = next(change for change in repository.db.bill_activity[-1].changes if change.kind == "item_removed")
    assert removed.before["currency"] == "BYN"
    encoded = json.dumps(serialize_to_dict(repository.db), cls=JsonEncoder)
    repository.db = parse_from_dict(json.loads(encoded))
    assert repository.get_next_bill_v2_id() == 8
