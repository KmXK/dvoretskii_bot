"""Tests for rule handlers: list, view, remove."""
from steward.data.models.rule import Response, Rule, RulePattern
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
        from steward.handlers.rule_handler import RuleListViewHandler

        reply, ok = await invoke(RuleListViewHandler, "/rule", repo_with_rules())
        assert ok
        assert "привет" in reply
        assert "пока" in reply

    async def test_empty_list(self):
        from steward.handlers.rule_handler import RuleListViewHandler

        reply, ok = await invoke(RuleListViewHandler, "/rule", make_repository())
        assert ok
        assert "Правила:" in reply

    async def test_ignores_command_with_args(self):
        from steward.handlers.rule_handler import RuleListViewHandler

        _, ok = await invoke(RuleListViewHandler, "/rule 1", make_repository())
        assert not ok


class TestRuleView:
    async def test_shows_existing_rule(self):
        from steward.handlers.rule_handler import RuleViewHandler

        reply, ok = await invoke(RuleViewHandler, "/rule 1", repo_with_rules())
        assert ok
        assert "привет" in reply
        assert "1" in reply

    async def test_nonexistent_rule(self):
        from steward.handlers.rule_handler import RuleViewHandler

        reply, ok = await invoke(RuleViewHandler, "/rule 999", repo_with_rules())
        assert ok
        assert "не существует" in reply

    async def test_invalid_id(self):
        from steward.handlers.rule_handler import RuleViewHandler

        reply, ok = await invoke(RuleViewHandler, "/rule notanumber", make_repository())
        assert ok
        assert "целым числом" in reply


class TestRuleRemove:
    async def test_removes_existing_rule(self):
        from steward.handlers.rule_handler import RuleRemoveHandler

        repo = repo_with_rules()
        await invoke(RuleRemoveHandler, "/rule remove 1", repo)
        assert not any(r.id == 1 for r in repo.db.rules)
        assert any(r.id == 2 for r in repo.db.rules)

    async def test_remove_nonexistent_rule(self):
        from steward.handlers.rule_handler import RuleRemoveHandler

        repo = repo_with_rules()
        reply, ok = await invoke(RuleRemoveHandler, "/rule remove 999", repo)
        assert ok
        assert "не существует" in reply
        assert len(repo.db.rules) == 2

    async def test_remove_multiple_rules(self):
        from steward.handlers.rule_handler import RuleRemoveHandler

        repo = repo_with_rules()
        await invoke(RuleRemoveHandler, "/rule remove 1 2", repo)
        assert len(repo.db.rules) == 0

    async def test_ignores_non_remove_command(self):
        from steward.handlers.rule_handler import RuleRemoveHandler

        _, ok = await invoke(RuleRemoveHandler, "/rule", make_repository())
        assert not ok
