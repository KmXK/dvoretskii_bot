"""Tests for BroadcastFeature: session activation and first step."""
from unittest.mock import MagicMock

from steward.data.models.chat import Chat
from steward.data.models.user import User
from steward.features.broadcast import BroadcastFeature
from tests.conftest import (
    CHAT_ID,
    DEFAULT_USER_ID,
    get_reply_text,
    make_context,
    make_repository,
)


def _make_feature(repo):
    feature = BroadcastFeature()
    feature.repository = repo
    feature.bot = MagicMock()
    return feature


class TestBroadcastFeature:
    async def test_no_group_chats(self):
        repo = make_repository()
        feature = _make_feature(repo)

        ctx = make_context("broadcast", repo=repo)
        ok = await feature.chat(ctx)
        assert ok
        reply = get_reply_text(ctx.message.reply_text)
        assert "нет" in reply.lower()

    async def test_shows_chat_selection_when_chats_available(self):
        repo = make_repository()
        repo.db.users = [User(id=DEFAULT_USER_ID, chat_ids=[CHAT_ID])]
        repo.db.chats = [Chat(id=CHAT_ID, name="Test Chat")]
        feature = _make_feature(repo)

        ctx = make_context("broadcast", repo=repo)
        ok = await feature.chat(ctx)
        assert ok
        reply = get_reply_text(ctx.message.reply_text)
        assert "чаты" in reply.lower() or "трансляц" in reply.lower()

    async def test_not_activated_on_other_commands(self):
        repo = make_repository()
        feature = _make_feature(repo)

        ctx = make_context("help", repo=repo)
        ok = await feature.chat(ctx)
        assert not ok
