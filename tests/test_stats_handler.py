"""Tests for StatsHandler: monkey leaderboard (DB) and metric display."""
from unittest.mock import AsyncMock, MagicMock

from steward.data.models.user import User
from steward.metrics.base import MetricSample
from tests.conftest import CHAT_ID, invoke, make_repository


def _metrics_mock():
    """AsyncMock-based metrics that returns empty results for Prometheus queries."""
    m = MagicMock()
    m.query = AsyncMock(return_value=[])
    return m


class TestStatsHandler:
    async def test_replies_with_stats(self):
        from steward.handlers.stats_handler import StatsHandler

        _, ok = await invoke(StatsHandler, "/stats", make_repository(), metrics=_metrics_mock())
        assert ok

    async def test_monkey_leaderboard_helper(self):
        from steward.handlers.stats_handler import StatsScope, _monkey_leaderboard

        repo = make_repository()
        repo.db.users = [
            User(id=1, username="alice", monkeys=500, chat_ids=[CHAT_ID]),
            User(id=2, username="bob", monkeys=200, chat_ids=[CHAT_ID]),
        ]
        entries = _monkey_leaderboard(repo, StatsScope.CHAT, str(CHAT_ID), top_n=3)
        assert len(entries) == 2
        assert entries[0] == ("alice", 500)
        assert entries[1] == ("bob", 200)

    async def test_no_monkey_data(self):
        from steward.handlers.stats_handler import StatsHandler

        repo = make_repository()
        repo.db.users = [User(id=1, username="alice", monkeys=0, chat_ids=[CHAT_ID])]
        reply, ok = await invoke(StatsHandler, "/stats", repo, metrics=_metrics_mock())
        assert ok
        assert "Нет данных" in reply or "📊" in reply

    async def test_curse_metric_detail_is_available(self):
        from steward.handlers.stats_handler import StatsHandler, StatsPeriod, StatsScope

        metrics = MagicMock()
        metrics.query = AsyncMock(
            return_value=[
                MetricSample(labels={"user_id": "1", "user_name": "alice"}, value=4),
            ]
        )
        repo = make_repository()
        handler = StatsHandler()
        handler.repository = repo
        handler.bot = MagicMock()

        text, _ = await handler._build_detail(metrics, repo, StatsScope.CHAT, StatsPeriod.DAY, 2, str(CHAT_ID))

        assert "🤬 Топ по мату" in text
        assert "alice" in text
