import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from steward.api import server
from steward.data.models.bill_v2 import BillItemAssignment, BillPaymentV2, BillPerson, BillTransaction, BillV2, PaymentStatus
from steward.data.models.user import User
from tests.conftest import make_repository


def setup_people(monkeypatch):
    repository = make_repository()
    repository.db.users = [
        User(id=1, username="caller", chat_ids=[-10, -20]),
        User(id=2, username="Mopahta", first_name="Павел", chat_ids=[-10]),
        User(id=3, username="outsider", chat_ids=[-30]),
        User(id=4, username="helper_bot", chat_ids=[-10], is_bot=True),
    ]
    repository.db.bill_persons = [
        BillPerson(id="caller", display_name="Кирилл", telegram_id=1, telegram_username="caller"),
        BillPerson(id="guest", display_name="@Mopahta"),
    ]
    repository._storage.write_dict = AsyncMock()
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda request: {"id": 1, "username": "caller"})
    return repository


def request_for(repository, data=None, bill_id=None):
    request = MagicMock()
    request.app = {"repository": repository}
    request.json = AsyncMock(return_value=data or {})
    request.match_info = {"id": str(bill_id)} if bill_id is not None else {}
    return request


async def test_circle_includes_shared_chat_user_without_previous_bills_and_persists_id(monkeypatch):
    repository = setup_people(monkeypatch)
    request = request_for(repository)

    response = await server.handle_bills_circle(request)
    people = json.loads(response.text)["people"]

    assert len(people) == 1
    assert people[0]["username"] == "Mopahta"
    assert people[0]["name"] == "Павел"
    person = repository.get_bill_person(people[0]["id"])
    assert person.telegram_id == 2
    assert person.id != "guest"
    repository._storage.write_dict.assert_awaited_once()
    saved = repository._storage.write_dict.call_args.args[0]
    assert any(p["id"] == person.id and p["telegram_id"] == 2 for p in saved["bill_persons"])

    again = json.loads((await server.handle_bills_circle(request)).text)["people"]
    assert again == people
    repository._storage.write_dict.assert_awaited_once()
    assert repository.get_bill_person_by_telegram_id(3) is None
    assert repository.get_bill_person_by_telegram_id(4) is None


@pytest.mark.parametrize("username", ["@Mopahta", "@mopahta", "MOPAHTA"])
async def test_resolve_then_create_keeps_real_telegram_participant(monkeypatch, username):
    repository = setup_people(monkeypatch)
    response = await server.handle_bills_resolve_people(request_for(repository, {
        "participants": [{"username": username}],
    }))
    people = json.loads(response.text)["people"]
    person = repository.get_bill_person_by_telegram_id(2)

    assert [p["id"] for p in people] == ["caller", person.id]
    assert people[1]["username"] == "Mopahta"
    response = await server.handle_bills_create(request_for(repository, {
        "name": "Общий ужин",
        "draft": True,
        "participants": [{"person_id": p["id"]} for p in people],
    }))
    assert response.status == 200
    assert json.loads(response.text)["participants"] == ["caller", person.id]


async def test_direct_create_and_edit_resolve_known_username_without_opening_circle(monkeypatch):
    repository = setup_people(monkeypatch)
    response = await server.handle_bills_create(request_for(repository, {
        "name": "Ужин", "participants": [{"username": "@Mopahta"}],
    }))
    bill = json.loads(response.text)
    person = repository.get_bill_person_by_telegram_id(2)
    assert bill["participants"] == ["caller", person.id]

    repository.db.bills_v2[0].participants = ["caller"]
    response = await server.handle_bills_set_participants(request_for(repository, {
        "participants": [{"username": "@Mopahta"}],
    }, bill_id=bill["id"]))
    assert json.loads(response.text)["participants"] == ["caller", person.id]


async def test_persons_refreshes_username_without_overwriting_saved_name_or_aliases(monkeypatch):
    repository = setup_people(monkeypatch)
    repository.db.bill_persons.append(BillPerson(
        id="pavel", display_name="Паша", telegram_id=2,
        telegram_username="old_username", aliases=["Павлик"],
    ))

    people = json.loads((await server.handle_bills_persons(request_for(repository))).text)

    assert {p["id"] for p in people} == {"caller", "pavel"}
    person = next(p for p in people if p["id"] == "pavel")
    assert person["telegram_username"] == "Mopahta"
    assert person["display_name"] == "Паша"
    assert person["aliases"] == ["Павлик"]


async def test_origin_chat_scope_does_not_include_people_from_another_shared_chat(monkeypatch):
    repository = setup_people(monkeypatch)
    response = await server.handle_bills_create(request_for(repository, {
        "name": "Другой чат", "origin_chat_id": -20,
        "participants": [{"username": "@Mopahta"}],
    }))

    assert response.status == 200
    assert repository.get_bill_person_by_telegram_id(2).id not in json.loads(response.text)["participants"]


async def test_unauthenticated_lookup_does_not_create_people(monkeypatch):
    repository = setup_people(monkeypatch)
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda request: None)

    assert (await server.handle_bills_circle(request_for(repository))).status == 401
    assert repository.get_bill_person_by_telegram_id(2) is None
    repository._storage.write_dict.assert_not_awaited()


async def test_temporary_person_has_owner_and_survives_resolve_create_handoff(monkeypatch):
    repository = setup_people(monkeypatch)
    response = await server.handle_bills_resolve_people(request_for(repository, {
        "participants": [{"name": "Новый гость"}],
    }))
    guest = json.loads(response.text)["people"][1]
    person = repository.get_bill_person(guest["id"])
    assert person.created_by_telegram_id == 1
    assert guest["created_by_me"] and guest["can_delete"]
    circle = json.loads((await server.handle_bills_circle(request_for(repository))).text)["people"]
    assert any(p["id"] == person.id for p in circle)

    response = await server.handle_bills_create(request_for(repository, {
        "name": "Ужин", "origin_chat_id": -10,
        "participants": [{"person_id": person.id}],
    }))
    assert person.id in json.loads(response.text)["participants"]
    request = request_for(repository)
    request.match_info = {"person_id": person.id}
    assert (await server.handle_bills_person_delete(request)).status == 409
    assert person.deleted_at is None


async def test_delete_own_guest_hides_picker_entry_and_preserves_closed_bill_names(monkeypatch):
    repository = setup_people(monkeypatch)
    person, _ = repository.get_or_create_anonymous_person("Мой гость", created_by_telegram_id=1)
    bill = BillV2(id=1, name="Прошлый ужин", author_person_id="caller", participants=["caller", person.id], transactions=[], closed=True)
    repository.db.bills_v2.append(bill)
    request = request_for(repository)
    request.match_info = {"person_id": person.id}

    assert (await server.handle_bills_person_delete(request)).status == 200
    assert repository.get_bill_person(person.id) is person
    assert person.deleted_at is not None
    assert person.id in bill.participants
    assert person not in repository.bill_persons_visible_to_user(1)
    circle = json.loads((await server.handle_bills_circle(request_for(repository))).text)["people"]
    assert person.id not in {p["id"] for p in circle}
    people = json.loads((await server.handle_bills_persons(request_for(repository))).text)
    archived = next(p for p in people if p["id"] == person.id)
    assert archived["display_name"] == "Мой гость"
    assert archived["deleted"] and not archived["can_delete"]
    resolved = json.loads((await server.handle_bills_resolve_people(request_for(repository, {
        "participants": [{"person_id": person.id}],
    }))).text)["people"]
    assert person.id not in {p["id"] for p in resolved}
    reopened = await server.handle_bills_reopen(request_for(repository, bill_id=bill.id))
    assert reopened.status == 200
    assert person.deleted_at is None
    assert person in repository.bill_persons_visible_to_user(1)


@pytest.mark.parametrize("creator,telegram_id,expected", [(2, None, 403), (None, None, 403), (1, 2, 409)])
async def test_delete_requires_creator_and_no_telegram_binding(monkeypatch, creator, telegram_id, expected):
    repository = setup_people(monkeypatch)
    person = BillPerson(id="protected", display_name="Участник", telegram_id=telegram_id, created_by_telegram_id=creator)
    repository.db.bill_persons.append(person)
    request = request_for(repository)
    request.match_info = {"person_id": person.id}

    assert (await server.handle_bills_person_delete(request)).status == expected
    assert person.deleted_at is None
    repository._storage.write_dict.assert_not_awaited()


@pytest.mark.parametrize("reference", ["draft", "author", "transaction", "pending_payment"])
async def test_delete_rejects_active_references(monkeypatch, reference):
    repository = setup_people(monkeypatch)
    person, _ = repository.get_or_create_anonymous_person("Гость", created_by_telegram_id=1)
    bill = BillV2(id=1, name="Ужин", author_person_id="caller", participants=["caller"], transactions=[])
    if reference == "draft":
        bill.distribution_status = "draft"
        bill.participants.append(person.id)
    elif reference == "author":
        bill.author_person_id = person.id
    elif reference == "transaction":
        bill.transactions = [BillTransaction(id="tx", item_name="Ужин", creditor="caller", assignments=[BillItemAssignment(1, [person.id])])]
    else:
        repository.db.bill_payments_v2.append(BillPaymentV2(id="p", debtor=person.id, creditor="caller", amount_minor=100, status=PaymentStatus.PENDING))
    repository.db.bills_v2.append(bill)
    request = request_for(repository)
    request.match_info = {"person_id": person.id}

    assert (await server.handle_bills_person_delete(request)).status == 409
    assert person.deleted_at is None


def test_same_named_guests_keep_separate_owners_and_deleted_guests_stay_deleted():
    from datetime import datetime

    repository = make_repository()
    legacy, _ = repository.get_or_create_anonymous_person("Саша")
    first, _ = repository.get_or_create_anonymous_person("Саша", created_by_telegram_id=1)
    second, _ = repository.get_or_create_anonymous_person("Саша", created_by_telegram_id=2)
    assert len({legacy.id, first.id, second.id}) == 3
    assert repository.get_or_create_anonymous_person("саша", created_by_telegram_id=1) == (first, False)
    first.deleted_at = datetime.now()
    fresh, created = repository.get_or_create_anonymous_person("Саша", created_by_telegram_id=1)
    assert created and fresh.id != first.id
    assert first.deleted_at is not None
