"""Tests for BroadcastSessionHandler: session activation and first step."""
from unittest.mock import MagicMock

from steward.data.models.chat import Chat
from steward.data.models.user import User
from tests.conftest import CHAT_ID, DEFAULT_USER_ID, get_reply_text, make_context, make_repository


def _make_handler(repo):
    from steward.handlers.broadcast_handler import BroadcastSessionHandler
    handler = BroadcastSessionHandler()
    handler.repository = repo
    handler.bot = MagicMock()
    return handler


class TestBroadcastSessionHandler:
    async def test_no_group_chats(self):
        """User has no group chats → error message, session stays inactive."""
        repo = make_repository()
        handler = _make_handler(repo)

        ctx = make_context("broadcast", repo=repo)
        ok = await handler.chat(ctx)
        assert ok
        reply = get_reply_text(ctx.message.reply_text)
        assert "нет" in reply.lower()

    async def test_shows_chat_selection_when_chats_available(self):
        """User has group chats → shows selection keyboard."""
        repo = make_repository()
        repo.db.users = [User(id=DEFAULT_USER_ID, chat_ids=[CHAT_ID])]
        repo.db.chats = [Chat(id=CHAT_ID, name="Test Chat")]
        handler = _make_handler(repo)

        ctx = make_context("broadcast", repo=repo)
        ok = await handler.chat(ctx)
        assert ok
        reply = get_reply_text(ctx.message.reply_text)
        assert "чаты" in reply.lower() or "трансляц" in reply.lower()

    async def test_not_activated_on_other_commands(self):
        """Handler does not activate on non-/broadcast commands."""
        repo = make_repository()
        handler = _make_handler(repo)

        ctx = make_context("help", repo=repo)
        ok = await handler.chat(ctx)
        assert not ok
        assert len(handler.sessions) == 0
