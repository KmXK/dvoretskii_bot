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
    accrue_curse_debt,
    apply_curse_interest_until,
    format_curse_debt_report,
    initialize_curse_debts,
    today_msk,
)
from steward.metrics.base import MetricSample
from tests.conftest import DEFAULT_USER_ID, make_repository


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
            items=[("Отжимания", 10)],
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
                items=[("Отжимания", 10)],
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


def test_applies_daily_compound_interest_until_target_date():
    repo = make_repository()
    repo.db.curse_punishments = [
        CursePunishment(id=1, coeff=4, title="приседаний", interest_percent=10.0)
    ]
    repo.db.curse_punishment_debts = [
        CursePunishmentDebt(
            id=1,
            user_id=DEFAULT_USER_ID,
            rule_id=1,
            punishment_count=100,
            last_interest_applied_date="2026-05-28",
        )
    ]

    changed = apply_curse_interest_until(repo, date(2026, 5, 30))

    assert changed is True
    assert repo.db.curse_punishment_debts[0].punishment_count == 121
    assert repo.db.curse_punishment_debts[0].last_interest_applied_date == "2026-05-30"


def test_interest_noops_when_already_applied_today():
    repo = make_repository()
    repo.db.curse_punishments = [
        CursePunishment(id=1, coeff=4, title="приседаний", interest_percent=10.0)
    ]
    repo.db.curse_punishment_debts = [
        CursePunishmentDebt(
            id=1,
            user_id=DEFAULT_USER_ID,
            rule_id=1,
            punishment_count=100,
            last_interest_applied_date="2026-05-30",
        )
    ]

    changed = apply_curse_interest_until(repo, date(2026, 5, 30))

    assert changed is False
    assert repo.db.curse_punishment_debts[0].punishment_count == 100


def test_interest_advances_cursor_even_for_zero_percent():
    repo = make_repository()
    repo.db.curse_punishments = [
        CursePunishment(id=1, coeff=4, title="приседаний", interest_percent=0.0)
    ]
    repo.db.curse_punishment_debts = [
        CursePunishmentDebt(
            id=1,
            user_id=DEFAULT_USER_ID,
            rule_id=1,
            punishment_count=100,
            last_interest_applied_date="2026-05-29",
        )
    ]

    changed = apply_curse_interest_until(repo, date(2026, 5, 30))

    assert changed is True
    assert repo.db.curse_punishment_debts[0].punishment_count == 100
    assert repo.db.curse_punishment_debts[0].last_interest_applied_date == "2026-05-30"


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
    repo.db.curse_punishments = [
        CursePunishment(id=1, coeff=10, title="приседаний", interest_percent=10.0)
    ]
    today_date = today_msk()
    yesterday = (today_date - date.resolution).isoformat()
    repo.db.curse_punishment_debts = [
        CursePunishmentDebt(
            id=1,
            user_id=DEFAULT_USER_ID,
            rule_id=1,
            punishment_count=100,
            last_interest_applied_date=yesterday,
        )
    ]
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
    repo.db.curse_punishments = [
        CursePunishment(id=1, coeff=10, title="приседаний", interest_percent=10.0)
    ]
    today_date = today_msk()
    yesterday = (today_date - date.resolution).isoformat()
    repo.db.curse_punishment_debts = [
        CursePunishmentDebt(
            id=1,
            user_id=DEFAULT_USER_ID,
            rule_id=1,
            punishment_count=100,
            last_interest_applied_date=yesterday,
        )
    ]
    action = CurseInterestDelayedAction(
        generator=ConstantGenerator(start=datetime.now(timezone.utc), period=date.resolution)
    )
    context = DelayedActionContext(repo, MagicMock(), MagicMock(), MagicMock())

    await action.execute(context)

    assert repo.db.curse_punishment_debts[0].punishment_count == 110
    assert repo.db.curse_punishment_debts[0].last_interest_applied_date == today_date.isoformat()
