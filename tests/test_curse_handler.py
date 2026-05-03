from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from steward.data.models.curse import CurseParticipant, CursePunishment
from steward.data.models.user import User
from steward.features.curse import CurseFeature
from steward.metrics.base import MetricSample
from tests.conftest import CHAT_ID, DEFAULT_USER_ID, invoke, make_repository


class TestCurseWordList:
    async def test_empty_list(self):
        reply, ok = await invoke(CurseFeature, "/curse word_list", make_repository())
        assert ok
        assert "пуст" in reply.lower()

    async def test_adds_words_for_admin(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, ok = await invoke(CurseFeature, "/curse word_list add Один ДВА", repo)
        assert ok
        assert repo.db.curse_words == {"один", "два"}
        assert "Добавлены" in reply

    async def test_rejects_add_for_non_admin(self):
        reply, ok = await invoke(CurseFeature, "/curse word_list add слово", make_repository())
        assert ok
        assert "прав" in reply.lower()


class TestCurseIncrement:
    async def test_increments_metric(self):
        metrics = MagicMock()
        reply, ok = await invoke(CurseFeature, "/curse 3", make_repository(), metrics=metrics)
        assert ok
        assert "3" in reply
        metrics.inc.assert_called_once_with("bot_curse_words_total", value=3)


class TestCursePunishment:
    async def test_adds_punishment_for_admin(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, ok = await invoke(CurseFeature, "/curse punishment add 5 отжиманий", repo)
        assert ok
        assert len(repo.db.curse_punishments) == 1
        assert repo.db.curse_punishments[0].coeff == 5
        assert "добавлено" in reply.lower()

    async def test_subscribe_and_show_today_for_current_chat_only(self):
        repo = make_repository()
        repo.db.users = [
            User(id=DEFAULT_USER_ID, username="testuser", chat_ids=[CHAT_ID]),
            User(id=999, username="other", chat_ids=[CHAT_ID + 1]),
        ]
        repo.db.curse_punishments = [CursePunishment(id=1, coeff=5, title="отжиманий")]
        repo.db.curse_participants = [
            CurseParticipant(
                user_id=DEFAULT_USER_ID,
                subscribed_at=datetime.now(timezone.utc),
                source_chat_ids=[CHAT_ID],
            ),
            CurseParticipant(
                user_id=999,
                subscribed_at=datetime.now(timezone.utc),
                source_chat_ids=[CHAT_ID + 1],
            ),
        ]

        metrics = MagicMock()
        metrics.query = AsyncMock(return_value=[MetricSample(labels={}, value=2)])

        reply, ok = await invoke(CurseFeature, "/curse punishment today", repo, metrics=metrics)
        assert ok
        assert "@testuser" in reply
        assert "10 отжиманий" in reply
        assert "@other" not in reply

    async def test_done_with_id_updates_metric_and_timestamp(self):
        repo = make_repository()
        repo.db.curse_punishments = [CursePunishment(id=2, coeff=4, title="приседаний")]
        participant = CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime.now(timezone.utc),
            source_chat_ids=[CHAT_ID],
        )
        repo.db.curse_participants = [participant]

        metrics = MagicMock()
        metrics.query = AsyncMock(return_value=[MetricSample(labels={}, value=3)])

        reply, ok = await invoke(CurseFeature, "/curse done 2", repo, metrics=metrics)
        assert ok
        assert "12 приседаний" in reply
        assert participant.last_done_at is not None
        metrics.inc.assert_called_once()

    async def test_subscribe_adds_chat_marker(self):
        repo = make_repository()
        reply, ok = await invoke(
            CurseFeature, "/curse punishment subscribe", repo, chat_id=CHAT_ID + 5
        )
        assert ok
        assert "включена" in reply.lower()
        assert repo.db.curse_participants[0].source_chat_ids == [CHAT_ID + 5]
