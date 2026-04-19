"""Tests for SubscribeFeature: view list and remove."""
import datetime

from steward.data.models.channel_subscription import ChannelSubscription
from steward.features.subscribe import SubscribeFeature
from tests.conftest import CHAT_ID, invoke, make_repository


def _sub(id: int, username: str = "testchannel") -> ChannelSubscription:
    return ChannelSubscription(
        id=id,
        channel_id=-100000000 - id,
        channel_username=username,
        chat_id=CHAT_ID,
        times=[datetime.time(9, 0)],
        last_post_id=0,
    )


class TestSubscribeView:
    async def test_empty(self):
        reply, ok = await invoke(SubscribeFeature, "/subscribe", make_repository())
        assert ok
        assert "нет подписок" in reply


class TestSubscribeRemove:
    async def test_removes_subscription(self):
        repo = make_repository()
        repo.db.channel_subscriptions = [_sub(1)]
        reply, ok = await invoke(SubscribeFeature, "/subscribe remove 1", repo)
        assert ok
        assert len(repo.db.channel_subscriptions) == 0
        assert "удалена" in reply

    async def test_not_found(self):
        reply, ok = await invoke(SubscribeFeature, "/subscribe remove 999", make_repository())
        assert ok
        assert "не найдена" in reply
