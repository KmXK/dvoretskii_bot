"""Tests for silence handlers: command and enforcer."""
import datetime
from unittest.mock import MagicMock

from tests.conftest import CHAT_ID, invoke, make_context, make_repository


class TestSilenceCommandHandler:
    async def test_enables_silence(self):
        from steward.handlers.silence_handler import SilenceCommandHandler

        repo = make_repository()
        reply, ok = await invoke(SilenceCommandHandler, "/silence 10m", repo)
        assert ok
        assert CHAT_ID in repo.db.silenced_chats
        assert "включен" in reply

    async def test_invalid_duration(self):
        from steward.handlers.silence_handler import SilenceCommandHandler

        reply, ok = await invoke(SilenceCommandHandler, "/silence notatime", make_repository())
        assert ok
        assert "распознать" in reply

    async def test_disable_when_active(self):
        from steward.handlers.silence_handler import SilenceCommandHandler

        repo = make_repository()
        repo.db.silenced_chats[CHAT_ID] = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        )
        reply, ok = await invoke(SilenceCommandHandler, "/silence off", repo)
        assert ok
        assert CHAT_ID not in repo.db.silenced_chats
        assert "отключен" in reply

    async def test_disable_when_inactive(self):
        from steward.handlers.silence_handler import SilenceCommandHandler

        reply, ok = await invoke(SilenceCommandHandler, "/silence off", make_repository())
        assert ok
        assert "уже отключён" in reply


class TestSilenceEnforcerHandler:
    def _make_handler(self, repo):
        from steward.handlers.silence_handler import SilenceEnforcerHandler
        handler = SilenceEnforcerHandler()
        handler.repository = repo
        handler.bot = MagicMock()
        return handler

    async def test_no_silence_passes_through(self):
        repo = make_repository()
        handler = self._make_handler(repo)
        ctx = make_context("hello", repo=repo)
        ok = await handler.chat(ctx)
        assert not ok

    async def test_active_silence_deletes_message(self):
        repo = make_repository()
        repo.db.silenced_chats[CHAT_ID] = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        )
        handler = self._make_handler(repo)
        ctx = make_context("hello", repo=repo)
        ok = await handler.chat(ctx)
        assert ok
        ctx.message.delete.assert_called_once()

    async def test_expired_silence_is_cleaned_up(self):
        repo = make_repository()
        repo.db.silenced_chats[CHAT_ID] = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        )
        handler = self._make_handler(repo)
        ctx = make_context("hello", repo=repo)
        ok = await handler.chat(ctx)
        assert not ok
        assert CHAT_ID not in repo.db.silenced_chats
