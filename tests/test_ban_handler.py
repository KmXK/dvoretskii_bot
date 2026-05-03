"""Tests for BanFeature command and BanEnforcerFeature."""
import datetime
from unittest.mock import MagicMock

from steward.data.models.banned_user import BannedUser
from steward.data.models.user import User
from steward.features.ban import BanEnforcerFeature, BanFeature
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


def _expired_ban(user_id: int) -> BannedUser:
    return BannedUser(
        chat_id=CHAT_ID,
        user_id=user_id,
        expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
    )


class TestBanCommand:
    async def test_no_args_shows_usage(self):
        reply, ok = await invoke(BanFeature, "/ban", make_repository())
        assert ok
        assert "Формат" in reply

    async def test_user_not_found(self):
        reply, ok = await invoke(BanFeature, "/ban @ghost 1h", make_repository())
        assert ok
        assert "не найден" in reply

    async def test_invalid_duration(self):
        repo = make_repository()
        repo.db.users = [_user(TARGET_ID)]
        reply, ok = await invoke(BanFeature, f"/ban {TARGET_ID} notaduration", repo)
        assert ok
        assert "распознать" in reply

    async def test_bans_user_by_id(self):
        repo = make_repository()
        repo.db.users = [_user(TARGET_ID, username="target")]
        reply, ok = await invoke(BanFeature, f"/ban {TARGET_ID} 1h", repo)
        assert ok
        assert any(b.user_id == TARGET_ID for b in repo.db.banned_users)
        assert "Бан" in reply

    async def test_bans_user_by_username(self):
        repo = make_repository()
        repo.db.users = [_user(TARGET_ID, username="target")]
        reply, ok = await invoke(BanFeature, "/ban @target 30m", repo)
        assert ok
        assert any(b.user_id == TARGET_ID for b in repo.db.banned_users)

    async def test_stop_clears_all_bans(self):
        repo = make_repository()
        repo.db.banned_users = [_active_ban(TARGET_ID)]
        reply, ok = await invoke(BanFeature, "/ban stop", repo)
        assert ok
        assert len(repo.db.banned_users) == 0
        assert "сняты" in reply

    async def test_stop_no_active_bans(self):
        reply, ok = await invoke(BanFeature, "/ban stop", make_repository())
        assert ok
        assert "активных" in reply

    async def test_stop_specific_user(self):
        repo = make_repository()
        repo.db.users = [_user(TARGET_ID, username="target")]
        repo.db.banned_users = [_active_ban(TARGET_ID)]
        reply, ok = await invoke(BanFeature, "/ban stop @target", repo)
        assert ok
        assert not any(b.user_id == TARGET_ID for b in repo.db.banned_users)
        assert "снят" in reply


class TestBanEnforcer:
    async def test_no_ban_passes_through(self):
        repo = make_repository()
        feature = BanEnforcerFeature()
        feature.repository = repo
        feature.bot = MagicMock()

        ctx = make_context("hello", repo=repo)
        ok = await feature.chat(ctx)
        assert not ok

    async def test_active_ban_deletes_message(self):
        repo = make_repository()
        repo.db.banned_users = [_active_ban(DEFAULT_USER_ID)]

        feature = BanEnforcerFeature()
        feature.repository = repo
        feature.bot = MagicMock()

        ctx = make_context("hello", repo=repo, user_id=DEFAULT_USER_ID)
        ok = await feature.chat(ctx)
        assert ok
        ctx.message.delete.assert_called_once()

    async def test_expired_ban_is_cleaned_up(self):
        repo = make_repository()
        repo.db.banned_users = [_expired_ban(DEFAULT_USER_ID)]

        feature = BanEnforcerFeature()
        feature.repository = repo
        feature.bot = MagicMock()

        ctx = make_context("hello", repo=repo, user_id=DEFAULT_USER_ID)
        ok = await feature.chat(ctx)
        assert not ok
        assert len(repo.db.banned_users) == 0
