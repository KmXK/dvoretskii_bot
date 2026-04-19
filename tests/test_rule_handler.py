"""Tests for RuleFeature: list, view, remove."""
from steward.data.models.rule import Response, Rule, RulePattern
from steward.features.rule import RuleFeature
from tests.conftest import invoke, make_repository


def _response():
    return Response(from_chat_id=0, message_id=0, probability=1000)


def repo_with_rules():
    repo = make_repository()
    repo.db.rules = [
        Rule(
            id=1,
            from_users=set(),
            pattern=RulePattern(regex="привет", ignore_case_flag=1),
            responses=[_response()],
            tags=[],
        ),
        Rule(
            id=2,
            from_users={12345},
            pattern=RulePattern(regex="пока", ignore_case_flag=0),
            responses=[_response()],
            tags=[],
        ),
    ]
    return repo


class TestRuleListView:
    async def test_shows_all_rules(self):
        reply, ok = await invoke(RuleFeature, "/rule", repo_with_rules())
        assert ok
        assert "привет" in reply
        assert "пока" in reply

    async def test_empty_list(self):
        reply, ok = await invoke(RuleFeature, "/rule", make_repository())
        assert ok
        assert "Правил нет" in reply or "Правила:" in reply


class TestRuleView:
    async def test_shows_existing_rule(self):
        reply, ok = await invoke(RuleFeature, "/rule 1", repo_with_rules())
        assert ok
        assert "привет" in reply
        assert "1" in reply

    async def test_nonexistent_rule(self):
        reply, ok = await invoke(RuleFeature, "/rule 999", repo_with_rules())
        assert ok
        assert "не существует" in reply


class TestRuleRemove:
    async def test_removes_existing_rule(self):
        repo = repo_with_rules()
        await invoke(RuleFeature, "/rule remove 1", repo)
        assert not any(r.id == 1 for r in repo.db.rules)
        assert any(r.id == 2 for r in repo.db.rules)

    async def test_remove_nonexistent_rule(self):
        repo = repo_with_rules()
        reply, ok = await invoke(RuleFeature, "/rule remove 999", repo)
        assert ok
        assert "не существует" in reply
        assert len(repo.db.rules) == 2

    async def test_remove_multiple_rules(self):
        repo = repo_with_rules()
        await invoke(RuleFeature, "/rule remove 1 2", repo)
        assert len(repo.db.rules) == 0
