import json
from datetime import datetime
from unittest.mock import MagicMock

from steward.api import tennis_routes
from steward.data.models.chat import Chat
from steward.data.models.tennis import TennisSession
from steward.data.models.user import User
from tests.conftest import make_repository


async def test_list_opponents_returns_every_user_from_shared_chats(monkeypatch):
    repository = make_repository()
    repository.db.chats = [
        Chat(id=-100, name="Настолки"),
        Chat(id=-200, name="Работа"),
        Chat(id=-300, name="Чужой чат"),
    ]
    repository.db.users = [
        User(id=1, username="me", first_name="Я", chat_ids=[-100, -200]),
        User(id=2, username="alice", first_name="Алиса", chat_ids=[-100]),
        User(id=3, username="bob", first_name="Борис", chat_ids=[-100, -200]),
        User(id=4, username="carol", first_name="Карина", chat_ids=[-300]),
    ]
    request = MagicMock()
    request.app = {"repository": repository}
    monkeypatch.setattr(tennis_routes, "require_user", lambda _: 1)

    response = await tennis_routes.list_opponents(request)
    payload = json.loads(response.text)

    assert [opponent["id"] for opponent in payload["opponents"]] == [2, 3]
    assert payload["opponents"][0]["name"] == "Алиса"
    assert payload["opponents"][0]["shared_chat_names"] == ["Настолки"]
    assert payload["opponents"][1]["shared_chat_names"] == ["Настолки", "Работа"]


async def test_list_opponents_keeps_previous_opponents_outside_shared_chats(monkeypatch):
    repository = make_repository()
    repository.db.users = [
        User(id=1, username="me", chat_ids=[-100]),
        User(id=2, username="alice", first_name="Алиса", chat_ids=[-200]),
    ]
    repository.db.tennis_sessions = [
        TennisSession(
            id=1,
            chat_id=1,
            player_a_id=1,
            player_b_id=2,
            started_at=datetime.now(),
        ),
    ]
    request = MagicMock()
    request.app = {"repository": repository}
    monkeypatch.setattr(tennis_routes, "require_user", lambda _: 1)

    response = await tennis_routes.list_opponents(request)
    payload = json.loads(response.text)

    assert payload["opponents"] == [
        {
            "id": 2,
            "username": "alice",
            "name": "Алиса",
            "shared_chats": [],
            "shared_chat_names": [],
            "played_against": 1,
        },
    ]
