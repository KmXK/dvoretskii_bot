"""Tests for SilenceFeature command and SilenceEnforcerFeature."""
import datetime
from unittest.mock import MagicMock

from steward.features.silence import SilenceEnforcerFeature, SilenceFeature
from tests.conftest import CHAT_ID, invoke, make_context, make_repository


class TestSilenceCommand:
    async def test_enables_silence(self):
        repo = make_repository()
        reply, ok = await invoke(SilenceFeature, "/silence 10m", repo)
        assert ok
        assert CHAT_ID in repo.db.silenced_chats
        assert "включен" in reply

    async def test_invalid_duration(self):
        reply, ok = await invoke(SilenceFeature, "/silence notatime", make_repository())
        assert ok
        assert "распознать" in reply

    async def test_disable_when_active(self):
        repo = make_repository()
        repo.db.silenced_chats[CHAT_ID] = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        )
        reply, ok = await invoke(SilenceFeature, "/silence off", repo)
        assert ok
        assert CHAT_ID not in repo.db.silenced_chats
        assert "отключен" in reply

    async def test_disable_when_inactive(self):
        reply, ok = await invoke(SilenceFeature, "/silence off", make_repository())
        assert ok
        assert "уже отключён" in reply


class TestSilenceEnforcer:
    def _make_feature(self, repo):
        feature = SilenceEnforcerFeature()
        feature.repository = repo
        feature.bot = MagicMock()
        return feature

    async def test_no_silence_passes_through(self):
        repo = make_repository()
        feature = self._make_feature(repo)
        ctx = make_context("hello", repo=repo)
        ok = await feature.chat(ctx)
        assert not ok

    async def test_active_silence_deletes_message(self):
        repo = make_repository()
        repo.db.silenced_chats[CHAT_ID] = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        )
        feature = self._make_feature(repo)
        ctx = make_context("hello", repo=repo)
        ok = await feature.chat(ctx)
        assert ok
        ctx.message.delete.assert_called_once()

    async def test_expired_silence_is_cleaned_up(self):
        repo = make_repository()
        repo.db.silenced_chats[CHAT_ID] = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        )
        feature = self._make_feature(repo)
        ctx = make_context("hello", repo=repo)
        ok = await feature.chat(ctx)
        assert not ok
        assert CHAT_ID not in repo.db.silenced_chats
