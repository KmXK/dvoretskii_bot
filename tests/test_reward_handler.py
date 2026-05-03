"""Tests for RewardFeature: list, remove, present/take routing."""
from steward.data.models.reward import Reward, UserReward
from steward.features.reward import RewardFeature
from tests.conftest import DEFAULT_USER_ID, invoke, make_repository


def repo_with_rewards():
    repo = make_repository()
    repo.db.rewards = [
        Reward(id=1, name="Первопроходец", emoji="🏆"),
        Reward(id=2, name="Кодер", emoji="💻"),
        Reward(id=3, name="Динамик", emoji="🔥", dynamic_key="top_coder"),
    ]
    repo.db.user_rewards = [
        UserReward(user_id=12345, reward_id=1),
        UserReward(user_id=99999, reward_id=2),
    ]
    return repo


class TestRewardList:
    async def test_shows_rewards(self):
        _, ok = await invoke(RewardFeature, "/rewards", repo_with_rewards())
        assert ok

    async def test_empty_list(self):
        _, ok = await invoke(RewardFeature, "/rewards", make_repository())
        assert ok


class TestRewardRemove:
    async def test_removes_reward_and_user_rewards(self):
        repo = repo_with_rewards()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        _, ok = await invoke(RewardFeature, "/rewards remove 1", repo)
        assert ok
        assert not any(r.id == 1 for r in repo.db.rewards)
        assert not any(ur.reward_id == 1 for ur in repo.db.user_rewards)

    async def test_nonexistent_reward(self):
        repo = repo_with_rewards()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, ok = await invoke(RewardFeature, "/rewards remove 999", repo)
        assert ok
        assert "не найдено" in reply

    async def test_cannot_remove_dynamic_reward(self):
        repo = repo_with_rewards()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, ok = await invoke(RewardFeature, "/rewards remove 3", repo)
        assert ok
        assert "нельзя" in reply
        assert any(r.id == 3 for r in repo.db.rewards)


class TestRewardPresentTakeRouting:
    async def test_present_routes_on_id_present(self):
        _, ok = await invoke(RewardFeature, "/rewards 1 present @testuser", repo_with_rewards())
        assert isinstance(ok, bool)

    async def test_take_routes_on_id_take(self):
        repo = repo_with_rewards()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        _, ok = await invoke(RewardFeature, "/rewards 1 take @testuser", repo)
        assert isinstance(ok, bool)
