from unittest.mock import AsyncMock, MagicMock

from steward.data.models.chat_settings import ChatSettings
from steward.data.models.bill_v2 import BillPerson, BillV2
from steward.data.models.user import User
from steward.features.settings import SettingsFeature
from tests.conftest import CHAT_ID, make_repository


def _settings_feature(repo):
    feature = SettingsFeature()
    feature.repository = repo
    feature.bot = MagicMock()
    return feature


def test_users_in_chat_excludes_bots_and_other_chats():
    repo = make_repository()
    repo.db.users = [
        User(id=1, username="alice", chat_ids=[CHAT_ID]),
        User(id=2, username="other", chat_ids=[CHAT_ID - 1]),
        User(id=3, username="helper_bot", chat_ids=[CHAT_ID], is_bot=True),
    ]

    assert [user.id for user in repo.users_in_chat(CHAT_ID)] == [1]
    assert repo.find_user_in_chat("@alice", CHAT_ID).id == 1
    assert repo.find_user_in_chat("@other", CHAT_ID) is None
    assert repo.find_user_in_chat("@helper_bot", CHAT_ID) is None


def test_admins_page_shows_only_humans_from_selected_chat():
    repo = make_repository()
    repo.db.admin_ids = {1}
    repo.db.users = [
        User(id=1, username="alice", chat_ids=[CHAT_ID]),
        User(id=2, username="other", chat_ids=[CHAT_ID - 1]),
        User(id=3, username="helper_bot", chat_ids=[CHAT_ID], is_bot=True),
    ]
    feature = _settings_feature(repo)
    ctx = MagicMock(repository=repo, user_id=1)

    members, render, _ = feature.admins_page(ctx, str(CHAT_ID))
    text = render(members)

    assert [user.id for user in members] == [1]
    assert "@alice" in text
    assert "@other" not in text
    assert "@helper_bot" not in text


async def test_admin_toggle_rejects_bot():
    repo = make_repository()
    repo.db.admin_ids = {1}
    repo.db.users = [
        User(id=1, username="alice", chat_ids=[CHAT_ID]),
        User(id=3, username="helper_bot", chat_ids=[CHAT_ID], is_bot=True),
    ]
    repo.db.chat_settings = [ChatSettings(chat_id=CHAT_ID)]
    feature = _settings_feature(repo)
    ctx = MagicMock(repository=repo, user_id=1)
    ctx.toast = AsyncMock()

    await feature.cb_admin_toggle(ctx, CHAT_ID, 3)

    ctx.toast.assert_awaited_once_with("Пользователь не состоит в этом чате")
    assert repo.db.chat_settings[0].chat_admins == set()


async def test_migration_marks_bots_and_removes_bot_chat_admins():
    repo = make_repository()
    data = {
        "version": 43,
        "users": [
            {"id": 1, "username": "alice", "chat_ids": [CHAT_ID]},
            {"id": 2, "username": "HelperBot", "chat_ids": [CHAT_ID]},
        ],
        "chat_settings": [
            {
                "chat_id": CHAT_ID,
                "enabled_capabilities": [],
                "disabled_features": [],
                "chat_admins": [1, 2],
                "onboarded": True,
            }
        ],
    }

    migrated = repo._migrate(data)

    assert migrated["version"] == 44
    assert migrated["users"][0]["is_bot"] is False
    assert migrated["users"][1]["is_bot"] is True
    assert migrated["chat_settings"][0]["chat_admins"] == [1]


def test_bill_people_visibility_uses_shared_chats_and_accessible_bills():
    repo = make_repository()
    repo.db.users = [
        User(id=1, username="alice", chat_ids=[CHAT_ID]),
        User(id=2, username="bob", chat_ids=[CHAT_ID]),
        User(id=3, username="other", chat_ids=[CHAT_ID - 1]),
        User(id=4, username="helper_bot", chat_ids=[CHAT_ID], is_bot=True),
    ]
    repo.db.bill_persons = [
        BillPerson(id="alice", display_name="Alice", telegram_id=1),
        BillPerson(id="bob", display_name="Bob", telegram_id=2),
        BillPerson(id="other", display_name="Other", telegram_id=3),
        BillPerson(id="bot", display_name="Bot", telegram_id=4),
        BillPerson(id="guest", display_name="Guest"),
    ]
    repo.db.bills_v2 = [
        BillV2(
            id=1,
            name="Dinner",
            author_person_id="alice",
            participants=["alice", "guest"],
            transactions=[],
            origin_chat_id=CHAT_ID,
        )
    ]

    visible_ids = {
        person.id
        for person in repo.bill_persons_visible_to_user(1)
    }

    assert visible_ids == {"alice", "bob", "guest"}
