"""Tests for StatsFeature: monkey leaderboard (DB) and metric display."""
from unittest.mock import AsyncMock, MagicMock

from steward.data.models.user import User
from steward.features.stats import (
    StatsFeature,
    _monkey_leaderboard,
    _Period,
    _Scope,
)
from steward.metrics.base import MetricSample
from tests.conftest import CHAT_ID, invoke, make_repository


def _metrics_mock():
    m = MagicMock()
    m.query = AsyncMock(return_value=[])
    return m


class TestStatsFeature:
    async def test_replies_with_stats(self):
        _, ok = await invoke(StatsFeature, "/stats", make_repository(), metrics=_metrics_mock())
        assert ok

    async def test_monkey_leaderboard_helper(self):
        repo = make_repository()
        repo.db.users = [
            User(id=1, username="alice", monkeys=500, chat_ids=[CHAT_ID]),
            User(id=2, username="bob", monkeys=200, chat_ids=[CHAT_ID]),
        ]
        entries = _monkey_leaderboard(repo, _Scope.CHAT, CHAT_ID, top_n=3)
        assert len(entries) == 2
        assert entries[0] == ("alice", 500)
        assert entries[1] == ("bob", 200)

    async def test_no_monkey_data(self):
        repo = make_repository()
        repo.db.users = [User(id=1, username="alice", monkeys=0, chat_ids=[CHAT_ID])]
        reply, ok = await invoke(StatsFeature, "/stats", repo, metrics=_metrics_mock())
        assert ok
        assert "Нет данных" in reply or "📊" in reply

    async def test_curse_metric_detail_is_available(self):
        metrics = MagicMock()
        metrics.query = AsyncMock(
            return_value=[
                MetricSample(labels={"user_id": "1", "user_name": "alice"}, value=4),
            ]
        )
        repo = make_repository()
        feature = StatsFeature()
        feature.repository = repo
        feature.bot = MagicMock()

        ctx = MagicMock()
        ctx.metrics = metrics
        ctx.repository = repo
        text, _ = await feature._build_detail(
            ctx, _Scope.CHAT, _Period.DAY, 2, CHAT_ID
        )

        assert "🤬 Топ по мату" in text
        assert "alice" in text
