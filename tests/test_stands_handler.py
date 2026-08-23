"""Tests for StandsFeature: list, multi-step add, remove."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import ForceReply

from steward.data.models.user import User
from steward.features import ai
from steward.features.stands import StandsFeature
from steward.session.session_registry import (
    session_last_activity,
    sessions,
    try_get_session_handler,
)
from tests.conftest import (
    CHAT_ID,
    DEFAULT_USER_ID,
    get_reply_text,
    invoke,
    make_context,
    make_repository,
    make_text_context,
)


def _user(
    user_id: int = DEFAULT_USER_ID,
    username: str = "testuser",
    stand_name: str | None = None,
    stand_description: str | None = None,
) -> User:
    return User(
        id=user_id, username=username,
        stand_name=stand_name, stand_description=stand_description,
        chat_ids=[CHAT_ID, -1001, -1002],
    )


def _make_feature(repo):
    feature = StandsFeature()
    feature.repository = repo
    feature.bot = MagicMock()
    return feature


@pytest.fixture(autouse=True)
def _clear_sessions():
    sessions.clear()
    session_last_activity.clear()
    yield
    sessions.clear()
    session_last_activity.clear()


async def _start_add(feature, repo, *, chat_id=None):
    kwargs = {"chat_id": chat_id} if chat_id is not None else {}
    ctx = make_context("stands", args="add StarPlatinum", repo=repo, **kwargs)
    ctx.update.message_reaction = None
    await feature.chat(ctx)
    session = try_get_session_handler(ctx.update)
    assert session is not None
    return ctx, session


class TestStandsView:
    async def test_empty_list(self):
        reply, ok = await invoke(StandsFeature, "/stands", make_repository())
        assert ok
        assert "нет" in reply

    async def test_shows_stands(self):
        repo = make_repository()
        repo.db.users = [
            _user(
                stand_name="StarPlatinum",
                stand_description="A powerful stand",
            )
        ]
        reply, ok = await invoke(StandsFeature, "/stands", repo)
        assert ok
        assert "StarPlatinum" in reply

    def test_ai_context_uses_only_stands_of_current_chat_members(self, monkeypatch):
        repo = make_repository()
        repo.db.users = [
            User(
                id=1,
                chat_ids=[-1001],
                stand_name="StarPlatinum",
                stand_description="first user",
            ),
            User(
                id=2,
                chat_ids=[-1001, -1002],
                stand_name="CrazyDiamond",
                stand_description="shared user",
            ),
        ]
        monkeypatch.setitem(ai._REPO_HOLDER, "repo", repo)

        block = ai._build_users_descriptions_block(-1002)

        assert "CrazyDiamond" in block
        assert "StarPlatinum" not in block


class TestStandsRemove:
    async def test_removes_stand(self):
        repo = make_repository()
        repo.db.users = [
            _user(stand_name="StarPlatinum", stand_description="desc")
        ]
        reply, ok = await invoke(StandsFeature, "/stands remove StarPlatinum", repo)
        assert ok
        assert "удален" in reply
        assert repo.db.users[0].stand_name is None
        assert repo.db.users[0].stand_description is None

    async def test_not_found(self):
        reply, ok = await invoke(StandsFeature, "/stands remove Unknown", make_repository())
        assert ok
        assert "не найден" in reply


class TestStandsAddFlow:
    async def test_add_start_prompts_description(self):
        repo = make_repository()
        repo.db.users = [_user()]
        feature = _make_feature(repo)

        ctx, _ = await _start_add(feature, repo)
        reply = get_reply_text(ctx.message.reply_text)
        assert "Добавляем" in reply
        force_reply = ctx.message.reply_text.call_args.kwargs["reply_markup"]
        assert isinstance(force_reply, ForceReply)
        assert force_reply.selective is True

    async def test_add_description_step_prompts_owner(self):
        repo = make_repository()
        repo.db.users = [_user()]
        feature = _make_feature(repo)

        _, session = await _start_add(feature, repo)

        ctx2 = make_text_context("A powerful stand", repo=repo, user_id=DEFAULT_USER_ID)
        ctx2.update.message_reaction = None
        await session.chat(ctx2)
        reply = get_reply_text(ctx2.message.reply_text)
        assert "владельца" in reply
        assert isinstance(
            ctx2.message.reply_text.call_args.kwargs["reply_markup"],
            ForceReply,
        )

    async def test_add_full_flow_saves_stand(self):
        repo = make_repository()
        repo.db.users = [_user()]
        feature = _make_feature(repo)
        feature._extract_aliases = AsyncMock()

        _, session = await _start_add(feature, repo)

        ctx2 = make_text_context("A powerful stand", repo=repo, user_id=DEFAULT_USER_ID)
        ctx2.update.message_reaction = None
        await session.chat(ctx2)

        ctx3 = make_text_context(str(DEFAULT_USER_ID), repo=repo, user_id=DEFAULT_USER_ID)
        ctx3.update.message_reaction = None
        await session.chat(ctx3)
        reply = get_reply_text(ctx3.message.reply_text)
        assert "Готово" in reply
        assert repo.db.users[0].stand_name == "StarPlatinum"
        assert repo.db.users[0].stand_description == "A powerful stand"
        assert try_get_session_handler(ctx3.update) is None

    async def test_unknown_owner_keeps_session_active(self):
        repo = make_repository()
        repo.db.users = [_user()]
        feature = _make_feature(repo)
        _, session = await _start_add(feature, repo)

        description = make_text_context("A powerful stand", repo=repo)
        description.update.message_reaction = None
        await session.chat(description)
        unknown = make_text_context("@missing", repo=repo)
        unknown.update.message_reaction = None
        await session.chat(unknown)

        assert "не найден" in get_reply_text(unknown.message.reply_text)
        assert try_get_session_handler(unknown.update) is session

    async def test_same_user_can_add_in_different_chats(self):
        repo = make_repository()
        repo.db.users = [_user()]
        feature = _make_feature(repo)

        ctx1, session1 = await _start_add(feature, repo, chat_id=-1001)
        ctx2, session2 = await _start_add(feature, repo, chat_id=-1002)

        assert session1 is session2
        assert len(session1.sessions) == 2
        assert try_get_session_handler(ctx1.update) is session1
        assert try_get_session_handler(ctx2.update) is session2

    async def test_list_filters_global_stands_by_chat_membership(self):
        repo = make_repository()
        repo.db.users = [
            User(
                id=1,
                chat_ids=[-1001],
                stand_name="StandOne",
                stand_description="first",
            ),
            User(
                id=2,
                chat_ids=[-1001, -1002],
                stand_name="StandTwo",
                stand_description="second",
            ),
            User(
                id=3,
                chat_ids=[-1002],
                stand_name="StandThree",
                stand_description="third",
            ),
        ]

        reply1, _ = await invoke(StandsFeature, "/stands", repo, chat_id=-1001)
        reply2, _ = await invoke(StandsFeature, "/stands", repo, chat_id=-1002)

        assert "StandOne" in reply1 and "StandTwo" in reply1
        assert "StandThree" not in reply1
        assert "StandTwo" in reply2 and "StandThree" in reply2
        assert "StandOne" not in reply2

    async def test_add_already_taken_stand_name(self):
        repo = make_repository()
        repo.db.users = [
            _user(stand_name="StarPlatinum", stand_description="desc")
        ]
        reply, ok = await invoke(StandsFeature, "/stands add StarPlatinum", repo)
        assert ok
        assert "уже привязан" in reply
