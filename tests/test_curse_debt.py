from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from steward.data.models.curse import (
    CurseParticipant,
    CursePunishment,
    CursePunishmentDebt,
    CursePunishmentDay,
)
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.curse_punishment_digest import (
    CurseInterestDelayedAction,
    CursePunishmentDigestDelayedAction,
)
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.helpers.curse_debt import (
    CurseDebtReportEntry,
    CurseDebtReportItem,
    accrue_curse_debt,
    apply_curse_interest_until,
    build_curse_debt_report_entries,
    format_curse_debt_report,
    format_curse_interest_forecast,
    initialize_curse_debts,
    reduce_curse_debt,
    today_msk,
)
from steward.data.models.user import User
from steward.metrics.base import MetricSample
from tests.conftest import CHAT_ID, DEFAULT_USER_ID, make_repository


def test_accrues_debt_only_for_selected_punishment_day():
    repo = make_repository()
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        )
    ]
    repo.db.curse_punishments = [
        CursePunishment(id=1, coeff=4, title="приседаний"),
        CursePunishment(id=2, coeff=2, title="отжиманий"),
    ]
    repo.db.curse_punishment_days = [
        CursePunishmentDay(date="2026-05-30", rule_id=2)
    ]

    changed = accrue_curse_debt(repo, DEFAULT_USER_ID, curse_count=3, today=date(2026, 5, 30))

    assert changed is True
    assert [(d.rule_id, d.punishment_count, d.last_interest_applied_date) for d in repo.db.curse_punishment_debts] == [
        (2, 6, "2026-05-30"),
    ]


def test_debt_report_mentions_users_by_default_for_digest():
    report = format_curse_debt_report([
        CurseDebtReportEntry(
            user_id=1,
            name="@test_user",
            items=[CurseDebtReportItem(title="Отжимания", count=10)],
        )
    ])

    assert "\n@test_user\n" in report
    assert "`@test_user`" not in report


def test_debt_report_can_wrap_users_in_monospace_for_manual_command():
    report = format_curse_debt_report(
        [
            CurseDebtReportEntry(
                user_id=1,
                name="@test_user",
                items=[CurseDebtReportItem(title="Отжимания", count=10)],
            )
        ],
        mention_users=False,
    )

    assert "`@test_user`" in report
    assert "\n@test_user\n" not in report


def test_accrue_selects_weighted_punishment_day_once_when_missing():
    repo = make_repository()
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        )
    ]
    repo.db.curse_punishments = [
        CursePunishment(id=1, coeff=4, title="приседаний", selection_weight=0.0),
        CursePunishment(id=2, coeff=2, title="отжиманий", selection_weight=3.5),
    ]

    changed = accrue_curse_debt(repo, DEFAULT_USER_ID, curse_count=3, today=date(2026, 5, 30))

    assert changed is True
    assert [(day.date, day.rule_id) for day in repo.db.curse_punishment_days] == [
        ("2026-05-30", 2)
    ]
    assert [(d.rule_id, d.punishment_count) for d in repo.db.curse_punishment_debts] == [
        (2, 6)
    ]


def test_accrues_into_existing_debt():
    repo = make_repository()
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        )
    ]
    repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="приседаний")]
    repo.db.curse_punishment_debts = [
        CursePunishmentDebt(
            id=1,
            user_id=DEFAULT_USER_ID,
            rule_id=1,
            punishment_count=8,
            last_interest_applied_date="2026-05-30",
        )
    ]

    changed = accrue_curse_debt(repo, DEFAULT_USER_ID, curse_count=2, today=date(2026, 5, 30))

    assert changed is True
    assert repo.db.curse_punishment_debts[0].punishment_count == 16


def test_does_not_accrue_for_unsubscribed_user():
    repo = make_repository()
    repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="приседаний")]

    changed = accrue_curse_debt(repo, DEFAULT_USER_ID, curse_count=2, today=date(2026, 5, 30))

    assert changed is False
    assert repo.db.curse_punishment_debts == []


def make_debt(repo, **overrides) -> CursePunishmentDebt:
    repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="Приседания")]
    debt = CursePunishmentDebt(
        id=1,
        user_id=DEFAULT_USER_ID,
        rule_id=1,
        punishment_count=overrides.pop("punishment_count", 100),
        last_interest_applied_date=overrides.pop("last_interest_applied_date", "2026-05-29"),
        **overrides,
    )
    repo.db.curse_punishment_debts = [debt]
    return debt


def test_new_debt_starts_at_one_percent():
    repo = make_repository()
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        )
    ]
    repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="Приседания")]

    accrue_curse_debt(repo, DEFAULT_USER_ID, curse_count=1, today=date(2026, 5, 30))

    assert repo.db.curse_punishment_debts[0].interest_percent == 1.0


def test_percent_grows_by_one_each_lazy_day():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=1000, interest_percent=5.0)

    changed = apply_curse_interest_until(repo, date(2026, 5, 30))

    assert changed is True
    assert debt.punishment_count == 1050
    assert debt.last_interest_delta == 50
    assert debt.interest_percent == 6.0
    assert debt.last_interest_percent_added == 1.0
    assert debt.last_interest_applied_date == "2026-05-30"


def test_percent_does_not_grow_when_half_of_accrual_is_done():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=25)

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.interest_percent == 5.0
    assert debt.last_interest_percent_added == 0.0
    assert debt.punishment_count == 1050
    assert debt.paid_since_interest == 0


def test_percent_grows_when_done_below_half_of_accrual():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=24)

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.interest_percent == 6.0


def test_percent_is_capped_at_hundred():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=10, interest_percent=100.0)

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.interest_percent == 100.0
    assert debt.last_interest_percent_added == 0.0
    assert debt.punishment_count == 20


def test_percent_compounds_over_missed_days():
    repo = make_repository()
    debt = make_debt(
        repo,
        punishment_count=100,
        interest_percent=1.0,
        last_interest_applied_date="2026-05-28",
    )

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.punishment_count == 104
    assert debt.interest_percent == 3.0


def test_done_counts_towards_threshold():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=1000, interest_percent=5.0)

    reduce_curse_debt(repo, DEFAULT_USER_ID, rule_id=1, count=30)

    assert debt.paid_since_interest == 30

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.interest_percent == 5.0


def test_interest_noops_when_already_applied_today():
    repo = make_repository()
    debt = make_debt(repo, last_interest_applied_date="2026-05-30")

    changed = apply_curse_interest_until(repo, date(2026, 5, 30))

    assert changed is False
    assert debt.punishment_count == 100


def test_disabled_participant_gets_no_interest_but_cursor_advances():
    repo = make_repository()
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            interest_enabled=False,
        )
    ]
    debt = make_debt(repo, punishment_count=1000, interest_percent=5.0)

    changed = apply_curse_interest_until(repo, date(2026, 5, 30))

    assert changed is True
    assert debt.punishment_count == 1000
    assert debt.interest_percent == 5.0
    assert debt.last_interest_delta == 0
    assert debt.last_interest_applied_date == "2026-05-30"


def test_report_shows_rate_accrual_and_growth():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0)
    apply_curse_interest_until(repo, date(2026, 5, 30))

    report = format_curse_debt_report(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Приседания: 1050" in report
    assert "Начислено за сутки: +50" in report
    assert "Ставка: 6% (+1% за пропуск)" in report


def test_report_says_rate_did_not_grow_when_threshold_met():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=25)
    apply_curse_interest_until(repo, date(2026, 5, 30))

    report = format_curse_debt_report(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Ставка: 5% (не поднялась)" in report


def test_report_omits_accrual_line_before_first_tick():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=1.0)

    report = format_curse_debt_report(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Ставка: 1%" in report
    assert "не поднялась" not in report
    assert "Начислено за сутки" not in report


def test_forecast_tells_how_much_is_left_to_avoid_growth():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=12)

    text = format_curse_interest_forecast(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "В полночь начислится +50 → 1050" in text
    assert "Сделано 12 из 25 — ещё 13, иначе ставка станет 6%" in text


def test_forecast_confirms_when_threshold_already_met():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=25)

    text = format_curse_interest_forecast(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Сделано 25 из 25 — ставка не вырастет" in text


def test_forecast_notes_rate_is_already_maxed():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=100.0)

    text = format_curse_interest_forecast(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "ставка уже максимальная" in text


def test_forecast_skips_users_with_interest_disabled():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            interest_enabled=False,
        )
    ]
    make_debt(repo, punishment_count=1000, interest_percent=5.0)

    text = format_curse_interest_forecast(build_curse_debt_report_entries(repo, CHAT_ID))

    assert text == ""


def test_report_marks_disabled_interest():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            interest_enabled=False,
        )
    ]
    make_debt(repo, punishment_count=1000, interest_percent=5.0)

    report = format_curse_debt_report(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Проценты отключены" in report
    assert "Ставка:" not in report


async def test_initialize_backfills_legacy_metric_debt_once():
    repo = make_repository()
    repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="приседаний")]
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
            done_words_offset=1,
        )
    ]
    metrics = AsyncMock()
    metrics.query = AsyncMock(return_value=[MetricSample(labels={}, value=3)])

    changed = await initialize_curse_debts(repo, metrics, today=date(2026, 5, 30))

    assert changed is True
    assert repo.db.curse_debts_backfilled is True
    assert repo.db.curse_punishment_debts[0].punishment_count == 8
    metrics.query.assert_called_once()


async def test_initialize_does_not_backfill_twice():
    repo = make_repository()
    repo.db.curse_debts_backfilled = True
    repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="приседаний")]
    metrics = AsyncMock()
    metrics.query = AsyncMock(return_value=[MetricSample(labels={}, value=3)])

    changed = await initialize_curse_debts(repo, metrics, today=date(2026, 5, 30))

    assert changed is False
    metrics.query.assert_not_called()


async def test_initialize_keeps_backfill_pending_when_metrics_fail():
    repo = make_repository()
    repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="приседаний")]
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
            done_words_offset=1,
        )
    ]
    metrics = AsyncMock()
    metrics.query = AsyncMock(side_effect=RuntimeError("victoriametrics is down"))

    changed = await initialize_curse_debts(repo, metrics, today=date(2026, 5, 30))

    assert changed is False
    assert repo.db.curse_debts_backfilled is False
    assert repo.db.curse_punishment_debts == []


async def test_digest_action_does_not_apply_interest_before_reporting():
    repo = make_repository()
    repo.db.users = []
    today_date = today_msk()
    yesterday = (today_date - date.resolution).isoformat()
    make_debt(repo, last_interest_applied_date=yesterday, interest_percent=10.0)
    action = CursePunishmentDigestDelayedAction(
        generator=ConstantGenerator(start=datetime.now(timezone.utc), period=date.resolution)
    )
    context = DelayedActionContext(repo, MagicMock(), MagicMock(), MagicMock())

    await action.execute(context)

    assert repo.db.curse_punishment_debts[0].punishment_count == 100
    assert repo.db.curse_punishment_debts[0].last_interest_applied_date == yesterday


async def test_interest_action_applies_interest():
    repo = make_repository()
    repo.db.users = []
    today_date = today_msk()
    yesterday = (today_date - date.resolution).isoformat()
    make_debt(repo, last_interest_applied_date=yesterday, interest_percent=10.0)
    action = CurseInterestDelayedAction(
        generator=ConstantGenerator(start=datetime.now(timezone.utc), period=date.resolution)
    )
    context = DelayedActionContext(repo, MagicMock(), MagicMock(), MagicMock())

    await action.execute(context)

    assert repo.db.curse_punishment_debts[0].punishment_count == 110
    assert repo.db.curse_punishment_debts[0].last_interest_applied_date == today_date.isoformat()
