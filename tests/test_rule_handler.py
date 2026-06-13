"""Tests for RuleFeature: list, view, remove."""
from unittest.mock import AsyncMock, MagicMock

from steward.data.models.rule import Response, Rule, RulePattern
from steward.features.rule import RuleFeature
from steward.features.rule_answer import RuleAnswerFeature
from steward.framework import FeatureContext
from tests.conftest import CHAT_ID, DEFAULT_USER_ID, invoke, make_repository, make_text_context

SERVICE_CHAT_ID = -1003876657662


def _callback_ctx(repo, user_id, chat_id, bot=None):
    """Минимальный FeatureContext для callback-обработчика."""
    cq = MagicMock()
    cq.from_user.id = user_id
    cq.message.chat.id = chat_id
    cq.answer = AsyncMock()
    cq.edit_message_text = AsyncMock()
    cq.edit_message_reply_markup = AsyncMock()
    update = MagicMock()
    update.message = None
    update.edited_message = None
    update.callback_query = cq
    return FeatureContext(
        update=update,
        tg_context=MagicMock(),
        repository=repo,
        bot=bot or AsyncMock(),
        client=MagicMock(),
        metrics=MagicMock(),
        message=None,
        callback_query=cq,
    )


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


async def _run_answer(repo, text, user_id=DEFAULT_USER_ID, chat_id=CHAT_ID):
    feature = RuleAnswerFeature()
    feature.repository = repo
    feature.bot = MagicMock()
    ctx = make_text_context(text, repo=repo, user_id=user_id, chat_id=chat_id)
    handled = await feature.chat(ctx)
    return bool(handled), ctx.message


def _scope_repo():
    repo = make_repository()
    repo.db.rules = [
        Rule(
            id=1,
            from_users={0},
            pattern=RulePattern(regex="привет", ignore_case_flag=1),
            responses=[Response(0, 0, 1000, text="хай")],
            tags=[],
            chats={CHAT_ID},
        )
    ]
    return repo


class TestRuleAnswerScope:
    async def test_answers_inside_scope(self):
        handled, msg = await _run_answer(_scope_repo(), "привет")
        assert handled
        msg.reply_text.assert_called()

    async def test_silent_outside_scope(self):
        handled, _ = await _run_answer(_scope_repo(), "привет", chat_id=-999000)
        assert not handled


class TestRuleAnswerFromUsers:
    async def test_specific_user_rule_not_triggered_by_other(self):
        # Регресс на старый баг: правило rule-1 от_users={999} не должно
        # срабатывать на другого юзера только потому, что rule-2 — «от всех».
        repo = make_repository()
        repo.db.rules = [
            Rule(
                id=1,
                from_users={999},
                pattern=RulePattern(regex="привет", ignore_case_flag=1),
                responses=[Response(0, 0, 1000, text="A")],
                tags=[],
                chats={CHAT_ID},
            ),
            Rule(
                id=2,
                from_users={0},
                pattern=RulePattern(regex="пока", ignore_case_flag=1),
                responses=[Response(0, 0, 1000, text="B")],
                tags=[],
                chats={CHAT_ID},
            ),
        ]
        handled, _ = await _run_answer(repo, "привет", user_id=DEFAULT_USER_ID)
        assert not handled


class TestRuleMigration:
    def test_global_rules_scoped_to_service_chat(self):
        repo = make_repository()
        data = {
            "version": 40,
            "rules": [
                {
                    "id": 1,
                    "from_users": [],
                    "pattern": {"regex": "x", "ignore_case_flag": 1},
                    "responses": [],
                    "tags": [],
                }
            ],
        }
        out = repo._migrate(data)
        assert out["rules"][0]["chats"] == [SERVICE_CHAT_ID]
        assert out["version"] >= 41


class TestRuleHelpers:
    def test_build_regex_middle_wraps(self):
        from steward.features.rule import _build_regex
        assert _build_regex("привет", "middle") == ".*привет.*"

    def test_build_regex_exact_anchors(self):
        from steward.features.rule import _build_regex
        assert _build_regex("привет", "exact") == "^привет$"

    def test_equal_probabilities_sum_1000(self):
        from steward.features.rule import _equal_probabilities
        for n in (1, 2, 3, 7, 13):
            probs = _equal_probabilities(n)
            assert len(probs) == n
            assert sum(probs) == 1000
            # разброс не больше 1 промилле между долями
            assert max(probs) - min(probs) <= 1

    def test_validate_probs(self):
        from steward.features.rule import _validate_probs
        assert _validate_probs([500, 500], 2) is None
        assert _validate_probs([500], 2) is not None  # длина не совпадает
        assert _validate_probs([600, 600], 2) is not None  # сумма > 1000
        assert _validate_probs([-1, 1001], 2) is not None  # вне диапазона

    def test_render_rule_shows_chats_and_all(self):
        from steward.features.rule import _render_rule
        rule = Rule(
            id=5,
            from_users={0},
            pattern=RulePattern(regex=".*хай.*", ignore_case_flag=1),
            responses=[Response(0, 0, 1000, text="hi")],
            tags=[],
            chats={CHAT_ID},
        )
        text = _render_rule(rule, None)
        assert "id: 5" in text
        assert "все" in text  # from_users={0}
        assert str(CHAT_ID) in text

    def test_proposal_render_hides_other_chats(self):
        from steward.features.rule import _render_rule_proposal
        rule = Rule(
            id=5,
            from_users={0},
            pattern=RulePattern(regex=".*хай.*", ignore_case_flag=1),
            responses=[Response(0, 0, 1000, text="hi")],
            tags=[],
            chats={CHAT_ID, -777000},
        )
        text = _render_rule_proposal(rule)
        # карточка для чужого чата не должна светить названия/список других чатов
        assert "Чаты" not in text
        assert str(CHAT_ID) not in text
        assert "Шаблон" in text


def _propose_rule():
    repo = make_repository()
    rule = Rule(
        id=1,
        from_users={0},
        pattern=RulePattern(regex=".*x.*", ignore_case_flag=1),
        responses=[Response(0, 0, 1000, text="ok")],
        tags=[],
        chats={CHAT_ID},
    )
    repo.db.rules = [rule]
    return repo, rule


class TestRuleProposal:
    async def test_accept_by_target_admin_adds_chat(self):
        repo, rule = _propose_rule()
        repo.is_chat_admin = lambda uid, cid: True  # нажавший — админ целевого
        feature = RuleFeature()
        feature.repository = repo
        feature.bot = AsyncMock()
        target = -555000
        ctx = _callback_ctx(repo, user_id=1, chat_id=target)
        await feature.cb_prop_accept(ctx, rule_id=1, chat_id=target, by=999)
        assert target in rule.chats

    async def test_accept_denied_for_non_admin(self):
        repo, rule = _propose_rule()
        repo.is_chat_admin = lambda uid, cid: False
        feature = RuleFeature()
        feature.repository = repo
        feature.bot = AsyncMock()
        target = -555000
        ctx = _callback_ctx(repo, user_id=2, chat_id=target)
        await feature.cb_prop_accept(ctx, rule_id=1, chat_id=target, by=999)
        assert target not in rule.chats
        ctx.callback_query.answer.assert_called()  # показан тост-отказ

    async def test_accept_wrong_chat_ignored(self):
        repo, rule = _propose_rule()
        repo.is_chat_admin = lambda uid, cid: True
        feature = RuleFeature()
        feature.repository = repo
        feature.bot = AsyncMock()
        # кнопка для chat=-555000, но нажали в другом чате
        ctx = _callback_ctx(repo, user_id=1, chat_id=-999000)
        await feature.cb_prop_accept(ctx, rule_id=1, chat_id=-555000, by=999)
        assert -555000 not in rule.chats

    async def test_decline_does_not_add(self):
        repo, rule = _propose_rule()
        repo.is_chat_admin = lambda uid, cid: True
        feature = RuleFeature()
        feature.repository = repo
        feature.bot = AsyncMock()
        target = -555000
        ctx = _callback_ctx(repo, user_id=1, chat_id=target)
        await feature.cb_prop_decline(ctx, rule_id=1, chat_id=target, by=999)
        assert target not in rule.chats

    async def test_propose_sends_request_to_target(self):
        repo, rule = _propose_rule()
        # юзер — админ скоупленного CHAT_ID (значит может открыть edit),
        # но НЕ админ целевого чата → ветка «предложить»
        repo.is_chat_admin = lambda uid, cid: cid == CHAT_ID
        feature = RuleFeature()
        feature.repository = repo
        feature.bot = AsyncMock()
        target = -555000
        ctx = _callback_ctx(repo, user_id=DEFAULT_USER_ID, chat_id=CHAT_ID, bot=AsyncMock())
        await feature.cb_chat_propose(ctx, rule_id=1, chat_id=target, owner_id=DEFAULT_USER_ID)
        # запрос ушёл в целевой чат
        ctx.bot.send_message.assert_called()
        assert target not in rule.chats  # пока не подтвердили — не добавлен
