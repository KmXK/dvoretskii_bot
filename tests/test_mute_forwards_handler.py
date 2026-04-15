"""Tests for /mute_forwards handlers."""
import datetime
from unittest.mock import MagicMock

from steward.data.models.banned_user import BannedUser
from steward.data.models.forward_mute import ForwardMute
from steward.data.models.user import User
from tests.conftest import CHAT_ID, DEFAULT_USER_ID, invoke, make_context, make_repository

TARGET_ID = 99999


def _user(user_id: int, username: str = "target") -> User:
    return User(id=user_id, username=username)


def _active_ban(user_id: int) -> BannedUser:
    return BannedUser(
        chat_id=CHAT_ID,
        user_id=user_id,
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    )


class TestMuteForwardsCommandHandler:
    async def test_no_args_shows_usage(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        reply, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards", make_repository())
        assert ok
        assert "Формат" in reply

    async def test_user_not_found(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        reply, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards @ghost", make_repository())
        assert ok
        assert "не найден" in reply

    async def test_adds_mute_by_id(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        repo = make_repository()
        repo.db.users = [_user(TARGET_ID, username="target")]
        reply, ok = await invoke(MuteForwardsCommandHandler, f"/mute_forwards {TARGET_ID}", repo)
        assert ok
        assert any(m.user_id == TARGET_ID and m.chat_id == CHAT_ID for m in repo.db.forward_mutes)
        assert "удал" in reply.lower()

    async def test_adds_mute_by_username(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        repo = make_repository()
        repo.db.users = [_user(TARGET_ID, username="target")]
        _, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards @target", repo)
        assert ok
        assert any(m.user_id == TARGET_ID for m in repo.db.forward_mutes)

    async def test_adds_duplicate_noop(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        repo = make_repository()
        repo.db.users = [_user(TARGET_ID, username="target")]
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=TARGET_ID)]
        reply, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards @target", repo)
        assert ok
        assert len(repo.db.forward_mutes) == 1
        assert "уже" in reply

    async def test_stop_clears_all(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        repo = make_repository()
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=TARGET_ID)]
        reply, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards stop", repo)
        assert ok
        assert len(repo.db.forward_mutes) == 0
        assert "сняты" in reply

    async def test_stop_specific_user(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        repo = make_repository()
        repo.db.users = [_user(TARGET_ID, username="target")]
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=TARGET_ID)]
        reply, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards stop @target", repo)
        assert ok
        assert not any(m.user_id == TARGET_ID for m in repo.db.forward_mutes)
        assert "снята" in reply

    async def test_stop_no_active(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        reply, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards stop", make_repository())
        assert ok
        assert "активных" in reply.lower() or "нет" in reply.lower()

    async def test_banned_sender_blocked_from_stop(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        repo = make_repository()
        repo.db.banned_users = [_active_ban(DEFAULT_USER_ID)]
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=TARGET_ID)]
        _, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards stop", repo)
        assert not ok
        assert len(repo.db.forward_mutes) == 1

    async def test_banned_admin_can_stop(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsCommandHandler

        repo = make_repository()
        repo.db.banned_users = [_active_ban(DEFAULT_USER_ID)]
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=TARGET_ID)]
        _, ok = await invoke(MuteForwardsCommandHandler, "/mute_forwards stop", repo)
        assert ok
        assert len(repo.db.forward_mutes) == 0


class TestMuteForwardsEnforcerHandler:
    async def test_no_forward_passes_through(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsEnforcerHandler

        repo = make_repository()
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=DEFAULT_USER_ID)]

        handler = MuteForwardsEnforcerHandler()
        handler.repository = repo
        handler.bot = MagicMock()

        ctx = make_context("hello", repo=repo, user_id=DEFAULT_USER_ID)
        ctx.message.forward_origin = None
        ctx.message.photo = None
        ctx.message.video = None
        ctx.message.caption = None
        ctx.message.text = "hi"
        ok = await handler.chat(ctx)
        assert not ok

    async def test_forward_from_muted_user_deleted(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsEnforcerHandler

        repo = make_repository()
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=DEFAULT_USER_ID)]

        handler = MuteForwardsEnforcerHandler()
        handler.repository = repo
        handler.bot = MagicMock()

        ctx = make_context("hello", repo=repo, user_id=DEFAULT_USER_ID)
        ctx.message.forward_origin = MagicMock()
        ok = await handler.chat(ctx)
        assert ok
        ctx.message.delete.assert_called_once()

    async def test_photo_with_caption_from_muted_user_deleted(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsEnforcerHandler

        repo = make_repository()
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=DEFAULT_USER_ID)]

        handler = MuteForwardsEnforcerHandler()
        handler.repository = repo
        handler.bot = MagicMock()

        ctx = make_context("hello", repo=repo, user_id=DEFAULT_USER_ID)
        ctx.message.forward_origin = None
        ctx.message.photo = [MagicMock()]
        ctx.message.video = None
        ctx.message.caption = "check this out"
        ctx.message.text = None
        ok = await handler.chat(ctx)
        assert ok
        ctx.message.delete.assert_called_once()

    async def test_plain_text_from_muted_user_passes(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsEnforcerHandler

        repo = make_repository()
        repo.db.forward_mutes = [ForwardMute(chat_id=CHAT_ID, user_id=DEFAULT_USER_ID)]

        handler = MuteForwardsEnforcerHandler()
        handler.repository = repo
        handler.bot = MagicMock()

        ctx = make_context("hello", repo=repo, user_id=DEFAULT_USER_ID)
        ctx.message.forward_origin = None
        ctx.message.photo = None
        ctx.message.video = None
        ctx.message.caption = None
        ctx.message.text = "just chatting"
        ok = await handler.chat(ctx)
        assert not ok

    async def test_forward_from_non_muted_user_passes(self):
        from steward.handlers.mute_forwards_handler import MuteForwardsEnforcerHandler

        repo = make_repository()
        handler = MuteForwardsEnforcerHandler()
        handler.repository = repo
        handler.bot = MagicMock()

        ctx = make_context("hello", repo=repo, user_id=DEFAULT_USER_ID)
        ctx.message.forward_origin = MagicMock()
        ok = await handler.chat(ctx)
        assert not ok
