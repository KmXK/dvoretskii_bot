"""Tests for MeFeature: user profile with rewards."""
from steward.data.models.reward import Reward, UserReward
from steward.data.models.user import User
from steward.features.me import MeFeature
from tests.conftest import invoke, make_repository

USER_ID = 12345


class TestMeFeature:
    async def test_profile_no_rewards(self):
        repo = make_repository()
        repo.db.users = [User(id=USER_ID, monkeys=42)]
        reply, ok = await invoke(MeFeature, "/me", repo, user_id=USER_ID)
        assert ok
        assert "42" in reply
        assert "нет" in reply

    async def test_profile_with_rewards(self):
        repo = make_repository()
        repo.db.users = [User(id=USER_ID, monkeys=10)]
        repo.db.rewards = [Reward(id=1, name="Чемпион", emoji="🏆")]
        repo.db.user_rewards = [UserReward(user_id=USER_ID, reward_id=1)]
        reply, ok = await invoke(MeFeature, "/me", repo, user_id=USER_ID)
        assert ok
        assert "🏆" in reply

    async def test_profile_unknown_user(self):
        repo = make_repository()
        reply, ok = await invoke(MeFeature, "/me", repo, user_id=USER_ID)
        assert ok
        assert "0" in reply
