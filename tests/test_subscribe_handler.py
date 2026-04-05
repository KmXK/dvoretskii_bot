"""Tests for subscribe handlers: view list and remove (non-session handlers)."""
from steward.data.models.channel_subscription import ChannelSubscription
from tests.conftest import CHAT_ID, invoke, make_repository

import datetime


def _sub(id: int, username: str = "testchannel") -> ChannelSubscription:
    return ChannelSubscription(
        id=id,
        channel_id=-100000000 - id,
        channel_username=username,
        chat_id=CHAT_ID,
        times=[datetime.time(9, 0)],
        last_post_id=0,
    )


class TestSubscribeViewHandler:
    async def test_empty(self):
        from steward.handlers.subscribe_handler import SubscribeViewHandler

        reply, ok = await invoke(SubscribeViewHandler, "/subscribe", make_repository())
        assert ok
        assert "нет подписок" in reply

    async def test_ignores_add_subcommand(self):
        from steward.handlers.subscribe_handler import SubscribeViewHandler

        _, ok = await invoke(SubscribeViewHandler, "/subscribe add", make_repository())
        assert not ok

    async def test_ignores_remove_subcommand(self):
        from steward.handlers.subscribe_handler import SubscribeViewHandler

        _, ok = await invoke(SubscribeViewHandler, "/subscribe remove 1", make_repository())
        assert not ok


class TestSubscribeRemoveHandler:
    async def test_removes_subscription(self):
        from steward.handlers.subscribe_handler import SubscribeRemoveHandler

        repo = make_repository()
        repo.db.channel_subscriptions = [_sub(1)]
        reply, ok = await invoke(SubscribeRemoveHandler, "/subscribe remove 1", repo)
        assert ok
        assert len(repo.db.channel_subscriptions) == 0
        assert "удалена" in reply

    async def test_not_found(self):
        from steward.handlers.subscribe_handler import SubscribeRemoveHandler

        reply, ok = await invoke(SubscribeRemoveHandler, "/subscribe remove 999", make_repository())
        assert ok
        assert "не найдена" in reply

    async def test_invalid_id(self):
        from steward.handlers.subscribe_handler import SubscribeRemoveHandler

        reply, ok = await invoke(SubscribeRemoveHandler, "/subscribe remove abc", make_repository())
        assert ok
        assert "Неверный" in reply

    async def test_ignores_non_remove(self):
        from steward.handlers.subscribe_handler import SubscribeRemoveHandler

        _, ok = await invoke(SubscribeRemoveHandler, "/subscribe", make_repository())
        assert not ok
