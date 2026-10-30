import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from steward.api import server
from steward.data.models.bill_v2 import BillPerson
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
