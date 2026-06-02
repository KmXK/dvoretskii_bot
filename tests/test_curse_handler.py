from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from steward.bot.context import CallbackBotContext
from steward.data.models.curse import (
    CurseParticipant,
    CursePunishment,
    CursePunishmentDebt,
    CursePunishmentDay,
)
from steward.data.models.role import Role, UserRole
from steward.data.models.user import User
from steward.features.curse import CurseFeature
from steward.framework.types import from_chat_context
from steward.helpers.curse_debt import today_msk
from steward.session.context import ChatStepContext
from tests.conftest import (
    CHAT_ID,
    DEFAULT_USER_ID,
    get_reply_text,
    invoke,
    make_context,
    make_text_context,
    make_repository,
)


def grant_curse_manage(repo, user_id: int | None = None) -> None:
    """Засеять роль «Идеолог» (gate-ит право curse.manage). Опционально
    добавить юзера в роль, чтобы он мог управлять матами/наказаниями."""
    repo.db.roles.append(Role(id=1, name="Идеолог", permissions={"curse.manage"}))
    if user_id is not None:
        repo.db.user_roles.append(UserRole(user_id=user_id, role_id=1))


def make_callback_context(data: str, repo, user_id: int = DEFAULT_USER_ID):
    callback_query = MagicMock()
    callback_query.data = data
    callback_query.from_user.id = user_id
    callback_query.message = MagicMock()
    callback_query.message.chat.id = CHAT_ID
    callback_query.message.chat.send_message = AsyncMock()
    callback_query.edit_message_text = AsyncMock()
    callback_query.edit_message_reply_markup = AsyncMock()
    callback_query.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = callback_query
    update.message = None
    update.edited_message = None
    update.message_reaction = None
    update.effective_user.id = user_id
    update.effective_message = callback_query.message
    update.effective_message.chat.id = CHAT_ID

    return CallbackBotContext(
        repository=repo,
        bot=MagicMock(),
        client=MagicMock(),
        update=update,
        tg_context=MagicMock(),
        metrics=MagicMock(),
        callback_query=callback_query,
    )


class TestCurseWordList:
    async def test_empty_list(self):
        reply, ok = await invoke(CurseFeature, "/curse word_list", make_repository())
        assert ok
        assert "пуст" in reply.lower()

    async def test_word_list_uses_expandable_quote(self):
        repo = make_repository()
        repo.db.curse_words = {"мат", "слово"}
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", args="word_list", repo=repo)

        handled = await handler.chat(ctx)

        assert handled is True
        reply = get_reply_text(ctx.message.reply_text)
        assert "<blockquote expandable>" in reply
        assert "<b>Матерные слова</b>" in reply
        assert "мат" in reply
        assert "слово" in reply
        assert ctx.message.reply_text.call_args.kwargs["parse_mode"] == "HTML"

    async def test_adds_words_for_admin(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, ok = await invoke(CurseFeature, "/curse word_list add Один ДВА", repo)
        assert ok
        assert repo.db.curse_words == {"один", "два"}
        assert "Добавлены" in reply

    async def test_adds_words_for_role_member(self):
        repo = make_repository()
        grant_curse_manage(repo, DEFAULT_USER_ID)

        reply, ok = await invoke(CurseFeature, "/curse word_list add Один ДВА", repo)

        assert ok
        assert repo.db.curse_words == {"один", "два"}
        assert "Добавлены" in reply

    async def test_rejects_add_for_non_role_member(self):
        repo = make_repository()
        # Право curse.manage gated ролью «Идеолог», но юзер не в роли
        # и не глобал-админ → отказ.
        grant_curse_manage(repo)

        reply, ok = await invoke(CurseFeature, "/curse word_list add слово", repo)

        assert ok
        assert "прав" in reply.lower()
        assert repo.db.curse_words == set()


class TestCurseIgnoreList:
    async def test_empty_ignore_list(self):
        reply, ok = await invoke(CurseFeature, "/curse ignore_list", make_repository())
        assert ok
        assert "исключ" in reply.lower()
        assert "пуст" in reply.lower()

    async def test_ignore_list_uses_expandable_quote(self):
        repo = make_repository()
        repo.db.curse_ignore_words = {"бляха", "бляшка"}
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", args="ignore_list", repo=repo)

        handled = await handler.chat(ctx)

        assert handled is True
        reply = get_reply_text(ctx.message.reply_text)
        assert "<blockquote expandable>" in reply
        assert "<b>Исключения</b>" in reply
        assert "бляха" in reply
        assert "бляшка" in reply
        assert ctx.message.reply_text.call_args.kwargs["parse_mode"] == "HTML"

    async def test_adds_ignore_words_for_admin(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, ok = await invoke(CurseFeature, "/curse ignore_list add Пиздец БЛЯХА", repo)
        assert ok
        assert repo.db.curse_ignore_words == {"пиздец", "бляха"}
        assert "Добавлены" in reply

    async def test_removes_ignore_words_for_admin(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_ignore_words = {"пиздец", "бляха"}
        reply, ok = await invoke(CurseFeature, "/curse ignore_list remove бляха", repo)
        assert ok
        assert repo.db.curse_ignore_words == {"пиздец"}
        assert "Удалены" in reply

    async def test_rejects_ignore_add_for_non_role_member(self):
        repo = make_repository()
        grant_curse_manage(repo)
        reply, ok = await invoke(CurseFeature, "/curse ignore_list add бляха", repo)
        assert ok
        assert "прав" in reply.lower()


class TestCurseIncrement:
    async def test_increments_metric(self):
        metrics = MagicMock()
        reply, ok = await invoke(CurseFeature, "/curse 3", make_repository(), metrics=metrics)
        assert ok
        assert "3" in reply
        metrics.inc.assert_called_once_with("bot_curse_words_total", value=3)

    async def test_root_command_shows_current_debts(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.users = [User(id=DEFAULT_USER_ID, username="testuser", chat_ids=[CHAT_ID])]
        repo.db.curse_punishments = [
            CursePunishment(id=1, coeff=5, title="Отжимания", selection_weight=1.0)
        ]
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=1,
                punishment_count=10,
                last_interest_applied_date=today,
            )
        ]

        reply, ok = await invoke(CurseFeature, "/curse", repo)

        assert ok
        assert "Наказание дня:" in reply
        assert "Наказание #1" in reply
        assert "Название: Отжимания" in reply
        assert repo.db.curse_punishment_days == [
            CursePunishmentDay(date=today, rule_id=1)
        ]
        assert "@testuser" in reply
        assert "Отжимания: 10" in reply

    async def test_root_command_wraps_usernames_in_monospace(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.users = [
            User(id=DEFAULT_USER_ID, username="test_user", chat_ids=[CHAT_ID])
        ]
        repo.db.curse_punishments = [
            CursePunishment(id=1, coeff=5, title="Отжимания", selection_weight=1.0)
        ]
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=1,
                punishment_count=10,
                last_interest_applied_date=today,
            )
        ]

        reply, ok = await invoke(CurseFeature, "/curse", repo)

        assert ok
        assert "`@test_user`" in reply
        assert "\n@test_user\n" not in reply

    async def test_root_command_explains_when_no_punishments_configured(self):
        reply, ok = await invoke(CurseFeature, "/curse", make_repository())

        assert ok
        assert "Наказания ещё не настроены." in reply


class TestCursePunishment:
    async def test_adds_punishment_for_admin(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, ok = await invoke(CurseFeature, "/curse punishment add 5 ОТЖИМАНИЯ", repo)
        assert ok
        assert len(repo.db.curse_punishments) == 1
        assert repo.db.curse_punishments[0].coeff == 5
        assert repo.db.curse_punishments[0].title == "Отжимания"
        assert "добавлено" in reply.lower()
        assert "Наказание #1" in reply
        assert "Название: Отжимания" in reply
        assert "Весовой коэффициент в наказании дня: 1.0" in reply

    async def test_punishment_add_without_args_starts_wizard(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", args="punishment add", repo=repo)

        handled = await handler.chat(ctx)

        assert handled is True
        assert "Введите название наказания" in get_reply_text(ctx.message.reply_text)
        assert repo.db.curse_punishments == []

    async def test_punishment_add_wizard_creates_rule(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", repo=repo)

        await handler.punishment_add_done(
            from_chat_context(ctx),
            title="ПРИСЕДАНИЯ",
            coeff=10,
            selection_weight=2.5,
            interest_percent=5.5,
        )

        assert repo.db.curse_punishments == [
            CursePunishment(
                id=1,
                coeff=10,
                title="Приседания",
                selection_weight=2.5,
                interest_percent=5.5,
            )
        ]
        reply = get_reply_text(ctx.message.reply_text)
        assert "добавлено" in reply.lower()
        assert "Наказание #1" in reply
        assert "Название: Приседания" in reply
        assert "Ежедневный процент на долг: 5.5%" in reply

    async def test_punishment_add_wizard_uses_expanded_questions(self):
        questions = [
            step.question({})
            if callable(step.question)
            else step.question
            for step in CurseFeature._wizards["curse:punishment:add"].build_steps()
        ]

        assert questions == [
            'Введите название наказания, например: "отжимания", "приседания"',
            "Введите сколько единиц наказания выполнять за один мат, например 1 отжимание -> 5 приседаний",
            "Введите весовой коэффициент данного наказания. Используется при выборе наказания дня. "
            "Например, вес отжиманий: 2, вес приседаний: 1, "
            "следовательно отжимания будут наказанием дня в 2 раза чаще приседаний",
            "Введите накопительный процент по наказанию. Если наказание не было выполнено день в день, "
            "то в следующий день наказание нужно будет выполнить с процентами. "
            "Например, 10 отжиманий было перенесено на следующий день, процент = 10, "
            "тогда на следующий день ты будешь должен выполнить 11 отжиманий, а не 10",
        ]

    async def test_punishment_add_wizard_accepts_numeric_coeff_message(self):
        step = CurseFeature._wizards["curse:punishment:add"].build_steps()[1]
        ctx = make_text_context("10")
        step_ctx = ChatStepContext(**ctx.__dict__, session_context={})

        assert await step.chat(step_ctx) is False
        assert await step.chat(step_ctx) is True

        assert step_ctx.session_context["coeff"] == 10
        assert "целое число" not in get_reply_text(ctx.message.reply_text)

    async def test_punishment_add_wizard_allows_role_member(self):
        repo = make_repository()
        grant_curse_manage(repo, DEFAULT_USER_ID)
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", repo=repo)

        await handler.punishment_add_done(
            from_chat_context(ctx),
            title="приседаний",
            coeff=10,
            selection_weight=2.5,
            interest_percent=5.5,
        )

        assert len(repo.db.curse_punishments) == 1
        assert "добавлено" in get_reply_text(ctx.message.reply_text).lower()

    async def test_show_punishments_uses_cards(self):
        repo = make_repository()
        repo.db.curse_punishments = [
            CursePunishment(
                id=1,
                coeff=5,
                title="Отжимания",
                selection_weight=1.0,
                interest_percent=1.5,
            ),
            CursePunishment(
                id=2,
                coeff=10,
                title="Приседания",
                selection_weight=2.0,
                interest_percent=0.0,
            ),
        ]

        reply, ok = await invoke(CurseFeature, "/curse punishment", repo)

        assert ok
        assert "Наказания:" in reply
        assert "Наказание #1" in reply
        assert "Название: Отжимания" in reply
        assert "Коэффициент: 5" in reply
        assert "Весовой коэффициент в наказании дня: 1.0" in reply
        assert "Ежедневный процент на долг: 1.5%" in reply
        assert "Наказание #2" in reply
        assert "Название: Приседания" in reply

    async def test_punishment_edit_shows_inline_field_buttons(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_punishments = [
            CursePunishment(
                id=1,
                coeff=10,
                title="Приседания",
                selection_weight=2.5,
                interest_percent=5.5,
            )
        ]
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", args="punishment edit 1", repo=repo)

        handled = await handler.chat(ctx)

        assert handled is True
        reply = get_reply_text(ctx.message.reply_text)
        assert "Название: Приседания" in reply
        assert "Коэффициент: 10" in reply
        assert "Весовой коэффициент в наказании дня: 2.5" in reply
        assert "Ежедневный процент на долг: 5.5%" in reply
        markup = ctx.message.reply_text.call_args.kwargs["reply_markup"]
        labels = [button.text for row in markup.inline_keyboard for button in row]
        assert labels == ["Название", "Коэффициент", "Вес", "Процент", "Удалить"]

    async def test_punishment_edit_callback_starts_field_wizard(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_punishments = [
            CursePunishment(id=1, coeff=10, title="приседаний", selection_weight=2.5)
        ]
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_callback_context("curse:punishment_edit|1|weight", repo)

        handled = await handler.callback(ctx)

        assert handled is True
        ctx.callback_query.message.chat.send_message.assert_called_once()
        assert (
            "Введите весовой коэффициент данного наказания"
            in ctx.callback_query.message.chat.send_message.call_args.args[0]
        )

    async def test_punishment_edit_callback_allows_role_member(self):
        repo = make_repository()
        grant_curse_manage(repo, DEFAULT_USER_ID)
        repo.db.curse_punishments = [
            CursePunishment(id=1, coeff=10, title="приседаний", selection_weight=2.5)
        ]
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_callback_context("curse:punishment_edit|1|weight", repo)

        handled = await handler.callback(ctx)

        assert handled is True
        ctx.callback_query.message.chat.send_message.assert_called_once()
        assert (
            "Введите весовой коэффициент данного наказания"
            in ctx.callback_query.message.chat.send_message.call_args.args[0]
        )

    async def test_punishment_edit_field_wizard_updates_weight(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_punishments = [
            CursePunishment(id=1, coeff=10, title="приседаний", selection_weight=2.5)
        ]
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", repo=repo)

        await handler.punishment_edit_field_done(
            from_chat_context(ctx),
            id=1,
            field="weight",
            value=4.5,
        )

        assert repo.db.curse_punishments[0].selection_weight == 4.5
        assert "изменено" in get_reply_text(ctx.message.reply_text).lower()

    async def test_punishment_edit_field_wizard_keeps_waiting_after_invalid_number(self):
        step = CurseFeature._wizards["curse:punishment:edit_field"].build_steps()[0]
        invalid_ctx = make_text_context("abc")
        step_ctx = ChatStepContext(
            **invalid_ctx.__dict__,
            session_context={"field": "interest"},
        )

        assert await step.chat(step_ctx) is False
        assert await step.chat(step_ctx) is False

        assert "Введи число не меньше нуля." in get_reply_text(
            invalid_ctx.message.reply_text
        )
        assert "value" not in step_ctx.session_context

        valid_ctx = make_text_context("2.5")
        step_ctx.update = valid_ctx.update
        step_ctx.message = valid_ctx.message

        assert await step.chat(step_ctx) is True
        assert step_ctx.session_context["value"] == 2.5

    async def test_removed_punishment_commands_are_not_in_help(self):
        help_text = CurseFeature().help()

        assert help_text is not None
        assert "/curse punishment day" not in help_text
        assert "/curse punishment coeff" not in help_text
        assert "/curse punishment interest" not in help_text
        assert "/curse punishment remove" not in help_text
        assert "/curse punishment rename" not in help_text

    async def test_subscribe_and_show_today_for_current_chat_only(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.users = [
            User(id=DEFAULT_USER_ID, username="testuser", chat_ids=[CHAT_ID]),
            User(id=999, username="other", chat_ids=[CHAT_ID + 1]),
        ]
        repo.db.curse_punishments = [CursePunishment(id=1, coeff=5, title="Отжимания")]
        repo.db.curse_participants = [
            CurseParticipant(
                user_id=DEFAULT_USER_ID,
                subscribed_at=datetime.now(timezone.utc),
                source_chat_ids=[CHAT_ID],
            ),
            CurseParticipant(
                user_id=999,
                subscribed_at=datetime.now(timezone.utc),
                source_chat_ids=[CHAT_ID + 1],
            ),
        ]
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=1,
                punishment_count=10,
                last_interest_applied_date=today,
            ),
            CursePunishmentDebt(
                id=2,
                user_id=999,
                rule_id=1,
                punishment_count=99,
                last_interest_applied_date=today,
            ),
        ]

        reply, ok = await invoke(CurseFeature, "/curse punishment today", repo)
        assert ok
        assert "@testuser" in reply
        assert "Отжимания: 10" in reply
        assert "@other" not in reply

    async def test_done_with_id_updates_metric_and_closes_debt(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.curse_punishments = [CursePunishment(id=2, coeff=4, title="приседаний")]
        repo.db.curse_participants = [
            CurseParticipant(user_id=DEFAULT_USER_ID, subscribed_at=datetime.now(timezone.utc))
        ]
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=2,
                punishment_count=12,
                last_interest_applied_date=today,
            )
        ]

        metrics = MagicMock()

        reply, ok = await invoke(CurseFeature, "/curse done 2", repo, metrics=metrics)
        assert ok
        assert "12 приседаний" in reply
        assert repo.db.curse_punishment_debts == []
        metrics.inc.assert_called_once()

    async def test_done_with_id_and_count_partially_reduces_debt(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.curse_punishments = [CursePunishment(id=2, coeff=4, title="приседаний")]
        repo.db.curse_participants = [
            CurseParticipant(user_id=DEFAULT_USER_ID, subscribed_at=datetime.now(timezone.utc))
        ]
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=2,
                punishment_count=12,
                last_interest_applied_date=today,
            )
        ]

        metrics = MagicMock()

        reply, ok = await invoke(CurseFeature, "/curse done 2 4", repo, metrics=metrics)
        assert ok
        assert "Засчитано: 4 приседаний" in reply
        assert "Осталось: 8 приседаний" in reply
        assert repo.db.curse_punishment_debts[0].punishment_count == 8
        metrics.inc.assert_called_once()

    async def test_done_with_id_and_count_allows_direct_units(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.curse_punishments = [CursePunishment(id=2, coeff=4, title="приседаний")]
        repo.db.curse_participants = [
            CurseParticipant(user_id=DEFAULT_USER_ID, subscribed_at=datetime.now(timezone.utc))
        ]
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=2,
                punishment_count=12,
                last_interest_applied_date=today,
            )
        ]

        metrics = MagicMock()

        reply, ok = await invoke(CurseFeature, "/curse done 2 5", repo, metrics=metrics)
        assert ok
        assert "Осталось: 7 приседаний" in reply
        assert repo.db.curse_punishment_debts[0].punishment_count == 7
        metrics.inc.assert_called_once()

    async def test_done_with_id_and_count_caps_overpay_and_closes(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.curse_punishments = [CursePunishment(id=2, coeff=4, title="приседаний")]
        repo.db.curse_participants = [
            CurseParticipant(user_id=DEFAULT_USER_ID, subscribed_at=datetime.now(timezone.utc))
        ]
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=2,
                punishment_count=12,
                last_interest_applied_date=today,
            )
        ]

        metrics = MagicMock()

        reply, ok = await invoke(CurseFeature, "/curse done 2 100", repo, metrics=metrics)
        assert ok
        assert "Долг закрыт" in reply
        assert repo.db.curse_punishment_debts == []
        metrics.inc.assert_called_once()

    async def test_subscribe_adds_chat_marker(self):
        repo = make_repository()
        reply, ok = await invoke(
            CurseFeature, "/curse subscribe", repo, chat_id=CHAT_ID + 5
        )
        assert ok
        assert "включена" in reply.lower()
        assert repo.db.curse_participants[0].source_chat_ids == [CHAT_ID + 5]

    async def test_unsubscribe_short_command(self):
        repo = make_repository()
        repo.db.curse_participants = [
            CurseParticipant(user_id=DEFAULT_USER_ID, subscribed_at=datetime.now(timezone.utc))
        ]

        reply, ok = await invoke(CurseFeature, "/curse unsubscribe", repo)

        assert ok
        assert "отключена" in reply.lower()
        assert repo.db.curse_participants == []

    async def test_edit_wizard_sets_punishment_interest_after_catchup(self):
        repo = make_repository()
        today_date = today_msk()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_punishments = [
            CursePunishment(id=1, coeff=10, title="приседаний", interest_percent=10.5)
        ]
        yesterday = (today_date - timedelta(days=1)).isoformat()
        today = today_date.isoformat()
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=1,
                punishment_count=100,
                last_interest_applied_date=yesterday,
            )
        ]
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", repo=repo)

        await handler.punishment_edit_field_done(
            from_chat_context(ctx),
            id=1,
            field="interest",
            value=20.5,
        )

        reply = get_reply_text(ctx.message.reply_text)
        assert "20.5" in reply
        assert repo.db.curse_punishments[0].interest_percent == 20.5
        assert repo.db.curse_punishment_debts[0].punishment_count == 111
        assert repo.db.curse_punishment_debts[0].last_interest_applied_date == today

    async def test_edit_wizard_updates_punishment_coeff_for_future_accrual(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_punishments = [
            CursePunishment(id=1, coeff=10, title="приседаний", interest_percent=0.0)
        ]
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_context("curse", repo=repo)

        await handler.punishment_edit_field_done(
            from_chat_context(ctx),
            id=1,
            field="coeff",
            value=15,
        )

        reply = get_reply_text(ctx.message.reply_text)
        assert "15" in reply
        assert repo.db.curse_punishments[0].coeff == 15

    async def test_edit_callback_rejects_punishment_remove_when_debt_exists(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_punishments = [CursePunishment(id=1, coeff=10, title="приседаний")]
        repo.db.curse_punishment_debts = [
            CursePunishmentDebt(
                id=1,
                user_id=DEFAULT_USER_ID,
                rule_id=1,
                punishment_count=10,
                last_interest_applied_date=today,
            )
        ]
        handler = CurseFeature()
        handler.repository = repo
        handler.bot = MagicMock()
        ctx = make_callback_context("curse:punishment_edit|1|delete", repo)

        handled = await handler.callback(ctx)

        assert handled is True
        ctx.callback_query.answer.assert_called_once()
        assert "долг" in ctx.callback_query.answer.call_args.kwargs["text"].lower()
        assert len(repo.db.curse_punishments) == 1
