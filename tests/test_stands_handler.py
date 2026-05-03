"""Tests for StandsFeature: list, multi-step add, remove."""
from unittest.mock import MagicMock

from steward.data.models.user import User
from steward.features.stands import StandsFeature
from tests.conftest import (
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
    )


def _make_feature(repo):
    feature = StandsFeature()
    feature.repository = repo
    feature.bot = MagicMock()
    return feature


class TestStandsView:
    async def test_empty_list(self):
        reply, ok = await invoke(StandsFeature, "/stands", make_repository())
        assert ok
        assert "нет" in reply

    async def test_shows_stands(self):
        repo = make_repository()
        repo.db.users = [_user(stand_name="StarPlatinum", stand_description="A powerful stand")]
        reply, ok = await invoke(StandsFeature, "/stands", repo)
        assert ok
        assert "StarPlatinum" in reply


class TestStandsRemove:
    async def test_removes_stand(self):
        repo = make_repository()
        repo.db.users = [_user(stand_name="StarPlatinum", stand_description="desc")]
        reply, ok = await invoke(StandsFeature, "/stands remove StarPlatinum", repo)
        assert ok
        assert "удален" in reply
        assert repo.db.users[0].stand_name is None

    async def test_not_found(self):
        reply, ok = await invoke(StandsFeature, "/stands remove Unknown", make_repository())
        assert ok
        assert "не найден" in reply


class TestStandsAddFlow:
    async def test_add_start_prompts_description(self):
        repo = make_repository()
        repo.db.users = [_user()]
        feature = _make_feature(repo)

        ctx = make_context("stands", args="add StarPlatinum", repo=repo)
        await feature.chat(ctx)
        reply = get_reply_text(ctx.message.reply_text)
        assert "Добавляем" in reply
        assert DEFAULT_USER_ID in feature._pending_add

    async def test_add_description_step_prompts_owner(self):
        repo = make_repository()
        repo.db.users = [_user()]
        feature = _make_feature(repo)

        ctx1 = make_context("stands", args="add StarPlatinum", repo=repo)
        await feature.chat(ctx1)

        ctx2 = make_text_context("A powerful stand", repo=repo, user_id=DEFAULT_USER_ID)
        await feature.chat(ctx2)
        reply = get_reply_text(ctx2.message.reply_text)
        assert "владельца" in reply

    async def test_add_full_flow_saves_stand(self):
        repo = make_repository()
        repo.db.users = [_user()]
        feature = _make_feature(repo)

        ctx1 = make_context("stands", args="add StarPlatinum", repo=repo)
        await feature.chat(ctx1)

        ctx2 = make_text_context("A powerful stand", repo=repo, user_id=DEFAULT_USER_ID)
        await feature.chat(ctx2)

        ctx3 = make_text_context(str(DEFAULT_USER_ID), repo=repo, user_id=DEFAULT_USER_ID)
        await feature.chat(ctx3)
        reply = get_reply_text(ctx3.message.reply_text)
        assert "Готово" in reply
        assert repo.db.users[0].stand_name == "StarPlatinum"
        assert repo.db.users[0].stand_description == "A powerful stand"

    async def test_add_already_taken_stand_name(self):
        repo = make_repository()
        repo.db.users = [_user(stand_name="StarPlatinum", stand_description="desc")]
        reply, ok = await invoke(StandsFeature, "/stands add StarPlatinum", repo)
        assert ok
        assert "уже привязан" in reply
