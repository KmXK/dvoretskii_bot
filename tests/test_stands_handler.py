"""Tests for StandsHandler: list, multi-step add, remove."""
from unittest.mock import MagicMock

from steward.data.models.user import User
from tests.conftest import DEFAULT_USER_ID, invoke, make_context, make_repository, make_text_context


def _user(user_id: int = DEFAULT_USER_ID, username: str = "testuser", stand_name: str = None, stand_description: str = None) -> User:
    return User(id=user_id, username=username, stand_name=stand_name, stand_description=stand_description)


def _make_handler(repo):
    from steward.handlers.stands_handler import StandsHandler
    handler = StandsHandler()
    handler.repository = repo
    handler.bot = MagicMock()
    return handler


class TestStandsViewHandler:
    async def test_empty_list(self):
        from steward.handlers.stands_handler import StandsHandler

        reply, ok = await invoke(StandsHandler, "/stands", make_repository())
        assert ok
        assert "нет" in reply

    async def test_shows_stands(self):
        from steward.handlers.stands_handler import StandsHandler

        repo = make_repository()
        repo.db.users = [_user(stand_name="StarPlatinum", stand_description="A powerful stand")]
        reply, ok = await invoke(StandsHandler, "/stands", repo)
        assert ok
        assert "StarPlatinum" in reply


class TestStandsRemove:
    async def test_removes_stand(self):
        from steward.handlers.stands_handler import StandsHandler

        repo = make_repository()
        repo.db.users = [_user(stand_name="StarPlatinum", stand_description="desc")]
        reply, ok = await invoke(StandsHandler, "/stands remove StarPlatinum", repo)
        assert ok
        assert "удален" in reply
        assert repo.db.users[0].stand_name is None

    async def test_not_found(self):
        from steward.handlers.stands_handler import StandsHandler

        reply, ok = await invoke(StandsHandler, "/stands remove Unknown", make_repository())
        assert ok
        assert "не найден" in reply


class TestStandsAddFlow:
    async def test_add_start_prompts_description(self):
        repo = make_repository()
        repo.db.users = [_user()]
        handler = _make_handler(repo)

        ctx = make_context("stands", args="add StarPlatinum", repo=repo)
        await handler.chat(ctx)
        from tests.conftest import get_reply_text
        reply = get_reply_text(ctx.message.reply_text)
        assert "Добавляем" in reply
        assert DEFAULT_USER_ID in handler._pending_add

    async def test_add_description_step_prompts_owner(self):
        repo = make_repository()
        repo.db.users = [_user()]
        handler = _make_handler(repo)

        # Step 1: initiate add
        ctx1 = make_context("stands", args="add StarPlatinum", repo=repo)
        await handler.chat(ctx1)

        # Step 2: send description
        ctx2 = make_text_context("A powerful stand", repo=repo, user_id=DEFAULT_USER_ID)
        await handler.chat(ctx2)
        from tests.conftest import get_reply_text
        reply = get_reply_text(ctx2.message.reply_text)
        assert "владельца" in reply

    async def test_add_full_flow_saves_stand(self):
        repo = make_repository()
        repo.db.users = [_user()]
        handler = _make_handler(repo)

        # Step 1: initiate add
        ctx1 = make_context("stands", args="add StarPlatinum", repo=repo)
        await handler.chat(ctx1)

        # Step 2: description
        ctx2 = make_text_context("A powerful stand", repo=repo, user_id=DEFAULT_USER_ID)
        await handler.chat(ctx2)

        # Step 3: owner identifier
        ctx3 = make_text_context(str(DEFAULT_USER_ID), repo=repo, user_id=DEFAULT_USER_ID)
        await handler.chat(ctx3)
        from tests.conftest import get_reply_text
        reply = get_reply_text(ctx3.message.reply_text)
        assert "Готово" in reply
        assert repo.db.users[0].stand_name == "StarPlatinum"
        assert repo.db.users[0].stand_description == "A powerful stand"

    async def test_add_already_taken_stand_name(self):
        repo = make_repository()
        repo.db.users = [_user(stand_name="StarPlatinum", stand_description="desc")]
        reply, ok = await invoke(
            __import__("steward.handlers.stands_handler", fromlist=["StandsHandler"]).StandsHandler,
            "/stands add StarPlatinum",
            repo,
        )
        assert ok
        assert "уже привязан" in reply
