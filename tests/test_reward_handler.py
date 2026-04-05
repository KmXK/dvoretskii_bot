"""Tests for reward handlers: list, remove, present/take routing."""
from steward.data.models.reward import Reward, UserReward
from tests.conftest import invoke, make_repository


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
        from steward.handlers.reward_handler import RewardListHandler

        _, ok = await invoke(RewardListHandler, "/rewards", repo_with_rewards())
        assert ok

    async def test_empty_list(self):
        from steward.handlers.reward_handler import RewardListHandler

        _, ok = await invoke(RewardListHandler, "/rewards", make_repository())
        assert ok

    async def test_ignores_remove_subcommand(self):
        from steward.handlers.reward_handler import RewardListHandler

        _, ok = await invoke(RewardListHandler, "/rewards remove 1", make_repository())
        assert not ok


class TestRewardRemove:
    async def test_removes_reward_and_user_rewards(self):
        from steward.handlers.reward_handler import RewardRemoveHandler

        repo = repo_with_rewards()
        _, ok = await invoke(RewardRemoveHandler, "/rewards remove 1", repo)
        assert ok
        assert not any(r.id == 1 for r in repo.db.rewards)
        assert not any(ur.reward_id == 1 for ur in repo.db.user_rewards)

    async def test_nonexistent_reward(self):
        from steward.handlers.reward_handler import RewardRemoveHandler

        reply, ok = await invoke(RewardRemoveHandler, "/rewards remove 999", repo_with_rewards())
        assert ok
        assert "не найдено" in reply

    async def test_cannot_remove_dynamic_reward(self):
        from steward.handlers.reward_handler import RewardRemoveHandler

        repo = repo_with_rewards()
        reply, ok = await invoke(RewardRemoveHandler, "/rewards remove 3", repo)
        assert ok
        assert "нельзя" in reply
        assert any(r.id == 3 for r in repo.db.rewards)

    async def test_invalid_id(self):
        from steward.handlers.reward_handler import RewardRemoveHandler

        reply, ok = await invoke(RewardRemoveHandler, "/rewards remove abc", make_repository())
        assert ok
        assert "числом" in reply


class TestRewardPresentTakeRouting:
    async def test_present_routes_on_id_present(self):
        from steward.handlers.reward_handler import RewardPresentHandler

        _, ok = await invoke(RewardPresentHandler, "/rewards 1 present @testuser", repo_with_rewards())
        assert isinstance(ok, bool)

    async def test_take_routes_on_id_take(self):
        from steward.handlers.reward_handler import RewardTakeHandler

        _, ok = await invoke(RewardTakeHandler, "/rewards 1 take @testuser", repo_with_rewards())
        assert isinstance(ok, bool)
