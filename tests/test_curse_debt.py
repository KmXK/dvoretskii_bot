from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from steward.data.models.curse import (
    CurseParticipant,
    CursePunishment,
    CursePunishmentDebt,
    CursePunishmentDay,
    CurseStreak,
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
    format_curse_debt_progress,
    format_curse_debt_report,
    format_curse_day_outcome,
    format_curse_day_plan,
    initialize_curse_debts,
    reduce_curse_debt,
    today_msk,
)
from steward.helpers.curse_streak import record_curses
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


def test_debt_report_does_not_render_users_as_mentions():
    report = format_curse_debt_report([
        CurseDebtReportEntry(
            user_id=1,
            name="@\u200btest_user",
            items=[CurseDebtReportItem(title="Отжимания", count=10)],
        )
    ])

    assert "<code>@\u200btest_user</code>" in report


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


def test_percent_has_no_upper_cap():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=10, interest_percent=100.0)

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.interest_percent == 101.0
    assert debt.punishment_count == 20


def test_triple_norm_drops_percent_and_skips_accrual():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=150)

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.punishment_count == 1000
    assert debt.interest_percent == 4.0
    assert debt.last_interest_delta == 0
    assert debt.last_interest_percent_added == -1.0


def test_just_below_triple_norm_still_accrues():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=149)

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.punishment_count == 1050
    assert debt.interest_percent == 5.0


def test_percent_never_drops_below_one():
    repo = make_repository()
    debt = make_debt(repo, punishment_count=1000, interest_percent=1.0, paid_since_interest=30)

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.interest_percent == 1.0
    assert debt.punishment_count == 1000
    assert debt.last_interest_percent_added == 0.0


def test_percent_drops_at_most_one_per_day():
    repo = make_repository()
    debt = make_debt(
        repo,
        punishment_count=1000,
        interest_percent=9.0,
        paid_since_interest=900,
        last_interest_applied_date="2026-05-28",
    )

    apply_curse_interest_until(repo, date(2026, 5, 30))

    assert debt.interest_percent == 9.0
    assert debt.punishment_count == 1080


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


def test_plan_tells_both_thresholds():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=12)

    text = format_curse_day_plan(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Приседания: 1000, ставка 5%, сделано 12" in text
    assert "Начислится +50, ставка вырастет до 6%" in text
    assert "Ещё 13 — ставка не вырастет, 138 — упадёт" in text


def test_plan_when_keep_threshold_met():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=25)

    text = format_curse_day_plan(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Начислится +50, ставка не вырастет" in text
    assert "Ещё 125 — и вместо начисления ставка упадёт на 1%" in text


def test_plan_when_down_threshold_met():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=150)

    text = format_curse_day_plan(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Норма перевыполнена: начисления не будет, ставка → 4%" in text


def test_plan_at_minimum_rate_says_rate_cannot_drop():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=1.0, paid_since_interest=30)

    text = format_curse_day_plan(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "ставка уже минимальная" in text


def test_plan_skips_users_with_interest_disabled():
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

    assert format_curse_day_plan(build_curse_debt_report_entries(repo, CHAT_ID)) == ""


def test_plan_matches_what_the_tick_actually_does():
    for paid in (0, 12, 25, 100, 149, 150, 400):
        repo = make_repository()
        repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
        debt = make_debt(
            repo, punishment_count=997, interest_percent=5.0, paid_since_interest=paid
        )
        item = build_curse_debt_report_entries(repo, CHAT_ID)[0].items[0]
        planned_delta = item.next_delta
        planned_grows = item.left_to_keep > 0
        planned_drops = item.left_to_down <= 0

        apply_curse_interest_until(repo, date(2026, 5, 30))

        applied = debt.last_interest_delta
        assert applied == (0 if planned_drops else planned_delta), paid
        assert (debt.last_interest_percent_added > 0) is (planned_grows and not planned_drops), paid
        assert (debt.last_interest_percent_added < 0) is planned_drops, paid


def test_progress_after_done_shows_forecast():
    repo = make_repository()
    make_debt(repo, punishment_count=1000, interest_percent=5.0)

    reduce_curse_debt(repo, DEFAULT_USER_ID, 1, 12)
    text = format_curse_debt_progress(repo, DEFAULT_USER_ID, 1)

    assert "До полуночи:" in text
    assert "Приседания: 988, ставка 5%, сделано 12" in text
    assert "Начислится +50, ставка вырастет до 6%" in text
    assert "Ещё 13 — ставка не вырастет, 138 — упадёт" in text


def test_progress_is_empty_when_debt_closed():
    repo = make_repository()
    make_debt(repo, punishment_count=10, interest_percent=5.0)

    reduce_curse_debt(repo, DEFAULT_USER_ID, 1, 10)

    assert format_curse_debt_progress(repo, DEFAULT_USER_ID, 1) == ""


def test_progress_is_empty_when_interest_disabled():
    repo = make_repository()
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            interest_enabled=False,
        )
    ]
    make_debt(repo, punishment_count=1000, interest_percent=5.0)

    reduce_curse_debt(repo, DEFAULT_USER_ID, 1, 12)

    assert format_curse_debt_progress(repo, DEFAULT_USER_ID, 1) == ""


def test_outcome_reports_accrual_and_growth():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0)
    apply_curse_interest_until(repo, date(2026, 5, 30))

    text = format_curse_day_outcome(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Приседания: 1000 → 1050 (+50), ставка 5% → 6%" in text


def test_outcome_reports_drop_without_accrual():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=150)
    apply_curse_interest_until(repo, date(2026, 5, 30))

    text = format_curse_day_outcome(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Приседания: 1000 — без начисления, ставка 5% → 4%" in text


def test_outcome_reports_unchanged_rate():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=5.0, paid_since_interest=25)
    apply_curse_interest_until(repo, date(2026, 5, 30))

    text = format_curse_day_outcome(build_curse_debt_report_entries(repo, CHAT_ID))

    assert "Приседания: 1000 → 1050 (+50), ставка 5% без изменений" in text


def test_outcome_empty_before_first_tick():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="test_user", chat_ids={CHAT_ID})]
    make_debt(repo, punishment_count=1000, interest_percent=1.0)

    assert format_curse_day_outcome(build_curse_debt_report_entries(repo, CHAT_ID)) == ""


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

    assert "Приседания: 1000 (проценты отключены)" in report
    assert "ставка" not in report


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


async def test_interest_action_sends_hourly_chart_for_all_chat_participants():
    repo = make_repository()
    completed_day = today_msk() - date.resolution
    other_chat = CHAT_ID - 1
    second_user_id = DEFAULT_USER_ID + 1
    repo.db.users = [
        User(id=DEFAULT_USER_ID, username="cursing", chat_ids=[CHAT_ID, other_chat]),
        User(id=second_user_id, username="clean", chat_ids=[CHAT_ID, other_chat]),
    ]
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            source_chat_ids=[CHAT_ID],
        ),
        CurseParticipant(
            user_id=second_user_id,
            subscribed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            source_chat_ids=[CHAT_ID],
        ),
    ]
    repo.db.curse_streaks = [CurseStreak(user_id=second_user_id, days=4)]
    record_curses(repo, DEFAULT_USER_ID, 2, completed_day, hour=18)
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    action = CurseInterestDelayedAction(
        generator=ConstantGenerator(
            start=datetime.now(timezone.utc),
            period=date.resolution,
        )
    )
    context = DelayedActionContext(repo, bot, MagicMock(), MagicMock())

    await action.execute(context)

    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == CHAT_ID
    text = bot.send_message.await_args.args[1]
    assert "cursing" in text
    assert "clean" in text
    bot.send_photo.assert_awaited_once()
    assert bot.send_photo.await_args.args[0] == CHAT_ID
    assert bot.send_photo.await_args.kwargs["photo"].name == (
        f"curse-{completed_day.isoformat()}.png"
    )
