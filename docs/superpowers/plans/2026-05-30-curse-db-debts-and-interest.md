# Curse DB Debts And Interest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move curse punishment debt accounting from Prometheus/VictoriaMetrics queries into `db.json`, while keeping metrics for graphs and adding daily compound interest on outstanding punishment balances.

**Architecture:** Keep `bot_curse_words_total` and `bot_curse_punishment_done_total` as analytics metrics, but stop using metrics as the source of truth for `/curse done` and `/curse punishment today`. Store one DB debt per `(user_id, punishment_rule_id)` with a `punishment_count` balance and `last_interest_applied_date` cursor. Add a focused helper for debt accrual, interest catch-up, and one-time migration/backfill from the old metric-based state.

**Tech Stack:** Python 3.12, existing feature framework, JSON repository/dataclasses/dacite, existing delayed actions, pytest.

---

## Current Context Snapshot

- Curse commands live in `steward/features/curse.py`.
- Passive curse counting lives in `steward/features/curse_metric.py`.
- Current punishment state lives in `steward/data/models/curse.py` as:
  - `CursePunishment(id, coeff, title)`
  - `CurseParticipant(user_id, subscribed_at, last_done_at, done_words_offset, source_chat_ids)`
- Current punishment debt is computed from `bot_curse_words_total` in `steward/helpers/curse_punishment.py`.
- Current delayed digest is `steward/delayed_action/curse_punishment_digest.py`.
- Current DB version is `35`.
- Metrics must remain for graphs. DB becomes authoritative only for debt.

Do not use `ast-index` in this repository; the user explicitly prohibited it for this work.

---

## File Structure

- Modify: `steward/data/models/curse.py`
  - Add `interest_percent` to `CursePunishment`.
  - Add `CursePunishmentDebt`.
  - Keep `CurseParticipant` for subscription/chat membership only; old `last_done_at` and `done_words_offset` remain for one-time backfill compatibility.
- Modify: `steward/data/models/db.py`
  - Add `curse_punishment_debts: list[CursePunishmentDebt]`.
  - Add `curse_debts_backfilled: bool`.
  - Bump `version` from `35` to `36`.
- Modify: `steward/data/repository.py`
  - Add `35 -> 36` migration and idempotent fix-ups.
- Create: `steward/helpers/curse_debt.py`
  - Debt accrual for curse words.
  - Interest catch-up.
  - Backfill from legacy metrics.
  - Formatting helpers for reports.
  - Logging for interest, rule changes, and debt completion.
- Modify: `steward/features/curse_metric.py`
  - Continue incrementing `bot_curse_words_total`.
  - Also accrue DB debts for subscribed users.
- Modify: `steward/features/curse.py`
  - `/curse <n>` increments DB debts as well as metrics.
  - `/curse punishment today` reads DB debts, not metrics, and runs interest catch-up first.
  - `/curse done <id>` and `/curse done <id> <count>` reduce DB debts by punishment rule id.
  - Add admin commands to update `coeff`, `interest_percent`, and `title`; interest update must catch up old interest first.
  - Existing `/curse punishment remove <id>` must refuse removal while non-zero debts reference the rule.
- Modify: `steward/delayed_action/curse_punishment_digest.py`
  - Run interest catch-up before building digest.
- Modify: `steward/bot/bot.py`
  - After repository migration and before polling work begins, run startup initialization for curse debts: one-time legacy backfill and interest catch-up.
- Tests:
  - Modify `tests/test_curse_repository.py`.
  - Modify `tests/test_curse_metric_handler.py`.
  - Modify `tests/test_curse_handler.py`.
  - Add `tests/test_curse_debt.py`.
  - Modify `tests/test_startup.py` only if startup helper import/registration needs coverage.

---

### Task 1: Add DB Models And Migration

**Files:**
- Modify: `steward/data/models/curse.py`
- Modify: `steward/data/models/db.py`
- Modify: `steward/data/repository.py`
- Test: `tests/test_curse_repository.py`

- [ ] **Step 1: Write failing migration tests**

Append these tests to `tests/test_curse_repository.py`:

```python
    async def test_migrate_adds_curse_debt_fields(self):
        repo = make_repository()

        migrated = repo._migrate({"version": 35, "admin_ids": []})

        assert migrated["version"] >= 36
        assert migrated["curse_punishment_debts"] == []
        assert migrated["curse_debts_backfilled"] is False

    async def test_migrate_adds_interest_percent_to_existing_punishments(self):
        repo = make_repository()

        migrated = repo._migrate(
            {
                "version": 35,
                "admin_ids": [],
                "curse_punishments": [{"id": 1, "coeff": 5, "title": "отжиманий"}],
            }
        )

        assert migrated["curse_punishments"][0]["interest_percent"] == 0.0
```

- [ ] **Step 2: Run migration tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_repository.py::TestCurseRepositoryMigration::test_migrate_adds_curse_debt_fields tests/test_curse_repository.py::TestCurseRepositoryMigration::test_migrate_adds_interest_percent_to_existing_punishments -q
```

Expected: FAIL because `curse_punishment_debts`, `curse_debts_backfilled`, and `interest_percent` do not exist yet.

- [ ] **Step 3: Add model fields**

Change `steward/data/models/curse.py` to:

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CursePunishment:
    id: int
    coeff: int
    title: str
    interest_percent: float = 0.0


@dataclass
class CursePunishmentDebt:
    id: int
    user_id: int
    rule_id: int
    punishment_count: int
    last_interest_applied_date: str


@dataclass
class CurseParticipant:
    user_id: int
    subscribed_at: datetime
    last_done_at: datetime | None = None
    done_words_offset: int = 0
    source_chat_ids: list[int] = field(default_factory=list)
```

- [ ] **Step 4: Add DB fields and bump version**

In `steward/data/models/db.py`, update imports:

```python
from .curse import CurseParticipant, CursePunishment, CursePunishmentDebt
```

Add the DB fields next to existing curse fields:

```python
    curse_participants: list[CurseParticipant] = field(default_factory=list)
    curse_punishments: list[CursePunishment] = field(default_factory=list)
    curse_punishment_debts: list[CursePunishmentDebt] = field(default_factory=list)
    curse_debts_backfilled: bool = False
    curse_words: set[str] = field(default_factory=set)
```

Change:

```python
    version: int = 35
```

to:

```python
    version: int = 36
```

- [ ] **Step 5: Add repository migration**

In `steward/data/repository.py`, after the `if data.get("version") == 34:` block:

```python
        if data.get("version") == 35:
            data.setdefault("curse_punishment_debts", [])
            data.setdefault("curse_debts_backfilled", False)
            for punishment in data.get("curse_punishments", []):
                punishment.setdefault("interest_percent", 0.0)
            data["version"] = 36
```

In the idempotent fix-up section before `return data`, add:

```python
        data.setdefault("curse_punishment_debts", [])
        data.setdefault("curse_debts_backfilled", False)
        for punishment in data.get("curse_punishments", []):
            punishment.setdefault("interest_percent", 0.0)
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_repository.py -q
```

Expected: PASS.

---

### Task 2: Add Debt Helper Core

**Files:**
- Create: `steward/helpers/curse_debt.py`
- Test: `tests/test_curse_debt.py`

- [ ] **Step 1: Write failing debt accrual tests**

Create `tests/test_curse_debt.py`:

```python
from datetime import date, datetime, timezone

from steward.data.models.curse import (
    CurseParticipant,
    CursePunishment,
    CursePunishmentDebt,
)
from steward.helpers.curse_debt import accrue_curse_debt
from tests.conftest import DEFAULT_USER_ID, make_repository


def test_accrues_debt_for_subscribed_user():
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

    changed = accrue_curse_debt(repo, DEFAULT_USER_ID, curse_count=3, today=date(2026, 5, 30))

    assert changed is True
    assert [(d.rule_id, d.punishment_count, d.last_interest_applied_date) for d in repo.db.curse_punishment_debts] == [
        (1, 12, "2026-05-30"),
        (2, 6, "2026-05-30"),
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
```

- [ ] **Step 2: Run new tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_debt.py -q
```

Expected: FAIL because `steward.helpers.curse_debt` does not exist.

- [ ] **Step 3: Implement debt accrual helper**

Create `steward/helpers/curse_debt.py`:

```python
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from steward.data.models.curse import CursePunishmentDebt
from steward.data.repository import Repository


logger = logging.getLogger(__name__)
_MSK = ZoneInfo("Europe/Minsk")


def today_msk() -> date:
    return datetime.now(_MSK).date()


def date_key(value: date) -> str:
    return value.isoformat()


def _next_debt_id(repo: Repository) -> int:
    return max((debt.id for debt in repo.db.curse_punishment_debts), default=0) + 1


def _is_subscribed(repo: Repository, user_id: int) -> bool:
    return any(participant.user_id == user_id for participant in repo.db.curse_participants)


def _find_debt(repo: Repository, user_id: int, rule_id: int) -> CursePunishmentDebt | None:
    return next(
        (
            debt
            for debt in repo.db.curse_punishment_debts
            if debt.user_id == user_id and debt.rule_id == rule_id
        ),
        None,
    )


def accrue_curse_debt(
    repo: Repository,
    user_id: int,
    curse_count: int,
    today: date,
) -> bool:
    if curse_count <= 0:
        return False
    if not _is_subscribed(repo, user_id):
        return False

    changed = False
    today_key = date_key(today)
    for rule in repo.db.curse_punishments:
        if rule.coeff <= 0:
            logger.warning(
                "curse debt accrual skipped invalid rule_id=%s coeff=%s",
                rule.id,
                rule.coeff,
            )
            continue
        delta = curse_count * rule.coeff
        debt = _find_debt(repo, user_id, rule.id)
        if debt is None:
            repo.db.curse_punishment_debts.append(
                CursePunishmentDebt(
                    id=_next_debt_id(repo),
                    user_id=user_id,
                    rule_id=rule.id,
                    punishment_count=delta,
                    last_interest_applied_date=today_key,
                )
            )
        else:
            debt.punishment_count += delta
        changed = True
        logger.debug(
            "curse debt accrued user_id=%s rule_id=%s curse_count=%s delta=%s",
            user_id,
            rule.id,
            curse_count,
            delta,
        )
    return changed
```

- [ ] **Step 4: Run debt tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_debt.py -q
```

Expected: PASS.

---

### Task 3: Add Interest Catch-Up Helper

**Files:**
- Modify: `steward/helpers/curse_debt.py`
- Test: `tests/test_curse_debt.py`

- [ ] **Step 1: Add failing interest tests**

Append to `tests/test_curse_debt.py`:

```python
from steward.helpers.curse_debt import apply_curse_interest_until


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
```

- [ ] **Step 2: Run interest tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_debt.py::test_applies_daily_compound_interest_until_target_date tests/test_curse_debt.py::test_interest_noops_when_already_applied_today tests/test_curse_debt.py::test_interest_advances_cursor_even_for_zero_percent -q
```

Expected: FAIL because `apply_curse_interest_until` is not implemented.

- [ ] **Step 3: Implement interest catch-up**

Add to `steward/helpers/curse_debt.py`:

```python
from datetime import timedelta
from math import ceil


def _parse_date_key(value: str) -> date:
    return date.fromisoformat(value)


def _rule_by_id(repo: Repository, rule_id: int):
    return next((rule for rule in repo.db.curse_punishments if rule.id == rule_id), None)


def apply_curse_interest_until(repo: Repository, target_date: date) -> bool:
    changed = False
    for debt in repo.db.curse_punishment_debts:
        if debt.punishment_count <= 0:
            continue
        rule = _rule_by_id(repo, debt.rule_id)
        if rule is None:
            logger.warning(
                "curse interest skipped missing rule_id=%s debt_id=%s user_id=%s",
                debt.rule_id,
                debt.id,
                debt.user_id,
            )
            continue

        current_date = _parse_date_key(debt.last_interest_applied_date)
        while current_date < target_date:
            next_date = current_date + timedelta(days=1)
            before = debt.punishment_count
            if rule.interest_percent > 0:
                debt.punishment_count = ceil(
                    debt.punishment_count * (100 + rule.interest_percent) / 100
                )
            debt.last_interest_applied_date = date_key(next_date)
            current_date = next_date
            changed = True
            logger.info(
                "curse interest applied debt_id=%s user_id=%s rule_id=%s title=%r date=%s percent=%s before=%s after=%s",
                debt.id,
                debt.user_id,
                rule.id,
                rule.title,
                debt.last_interest_applied_date,
                rule.interest_percent,
                before,
                debt.punishment_count,
            )
    return changed
```

- [ ] **Step 4: Run debt tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_debt.py -q
```

Expected: PASS.

---

### Task 4: Add Legacy Backfill From Metrics At Startup

**Files:**
- Modify: `steward/helpers/curse_debt.py`
- Modify: `steward/bot/bot.py`
- Test: `tests/test_curse_debt.py`

- [ ] **Step 1: Add failing backfill tests**

Append to `tests/test_curse_debt.py`:

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from steward.helpers.curse_debt import initialize_curse_debts
from steward.metrics.base import MetricSample


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
```

- [ ] **Step 2: Run backfill tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_debt.py::test_initialize_backfills_legacy_metric_debt_once tests/test_curse_debt.py::test_initialize_does_not_backfill_twice -q
```

Expected: FAIL because `initialize_curse_debts` is not implemented.

- [ ] **Step 3: Implement startup initialization**

Add imports to `steward/helpers/curse_debt.py`:

```python
from steward.helpers.curse_punishment import get_current_curse_count
```

Add:

```python
async def initialize_curse_debts(repo: Repository, metrics, today: date) -> bool:
    changed = apply_curse_interest_until(repo, today)

    if repo.db.curse_debts_backfilled:
        return changed

    for participant in repo.db.curse_participants:
        since = participant.last_done_at or participant.subscribed_at
        raw_count = await get_current_curse_count(metrics, participant.user_id, since)
        effective_words = max(raw_count - (participant.done_words_offset or 0), 0)
        if effective_words <= 0:
            continue
        if accrue_curse_debt(repo, participant.user_id, effective_words, today):
            changed = True
            logger.info(
                "curse debt backfilled user_id=%s words=%s since=%s",
                participant.user_id,
                effective_words,
                since,
            )

    repo.db.curse_debts_backfilled = True
    changed = True
    logger.info("curse debt backfill completed")
    return changed
```

- [ ] **Step 4: Wire startup initialization into bot startup**

In `steward/bot/bot.py`, import:

```python
from steward.helpers.curse_debt import initialize_curse_debts, today_msk
```

The file already imports `asyncio`, `logging`, and other dependencies. Extend the existing import section carefully without duplicating imports.

In `post_init`, after:

```python
            await self.repository.migrate()
            await self.hints_updater.start(application.bot)
```

add:

```python
            if await initialize_curse_debts(self.repository, self.metrics, today_msk()):
                await self.repository.save()
```

- [ ] **Step 5: Run backfill and startup tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_debt.py tests/test_startup.py -q
```

Expected: PASS.

---

### Task 5: Accrue DB Debts From Passive Curse Counting

**Files:**
- Modify: `steward/features/curse_metric.py`
- Test: `tests/test_curse_metric_handler.py`

- [ ] **Step 1: Add failing metric accrual test**

Append to `tests/test_curse_metric_handler.py`:

```python
from datetime import datetime, timezone

from steward.data.models.curse import CurseParticipant, CursePunishment
from tests.conftest import DEFAULT_USER_ID


    async def test_accrues_db_debt_for_subscribed_user(self):
        repo = make_repository()
        repo.db.curse_words = {"мат"}
        repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="приседаний")]
        repo.db.curse_participants = [
            CurseParticipant(user_id=DEFAULT_USER_ID, subscribed_at=datetime.now(timezone.utc))
        ]
        metrics = MagicMock()
        feature = _make_feature(repo)

        ctx = make_text_context("мат мат", repo=repo, metrics=metrics)
        ok = await feature.chat(ctx)

        assert not ok
        metrics.inc.assert_called_once_with("bot_curse_words_total", value=2)
        assert len(repo.db.curse_punishment_debts) == 1
        assert repo.db.curse_punishment_debts[0].user_id == DEFAULT_USER_ID
        assert repo.db.curse_punishment_debts[0].rule_id == 1
        assert repo.db.curse_punishment_debts[0].punishment_count == 8
```

Place the imports at the top of the file, and place the test inside `class TestCurseMetricFeature`.

- [ ] **Step 2: Run new metric test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_metric_handler.py::TestCurseMetricFeature::test_accrues_db_debt_for_subscribed_user -q
```

Expected: FAIL because passive counting only increments metrics.

- [ ] **Step 3: Update passive feature to accrue DB debt**

In `steward/features/curse_metric.py`, import:

```python
from steward.helpers.curse_debt import accrue_curse_debt, today_msk
```

After:

```python
        if count > 0:
            ctx.metrics.inc("bot_curse_words_total", value=count)
```

add:

```python
            if accrue_curse_debt(self.repository, ctx.user_id, count, today_msk()):
                await self.repository.save()
```

- [ ] **Step 4: Run curse metric tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_metric_handler.py -q
```

Expected: PASS.

---

### Task 6: Convert Report And Done Commands To DB Debts

**Files:**
- Modify: `steward/helpers/curse_debt.py`
- Modify: `steward/features/curse.py`
- Test: `tests/test_curse_handler.py`

- [ ] **Step 1: Add failing DB report and done tests**

Update existing `TestCursePunishment` tests in `tests/test_curse_handler.py` so they use `repo.db.curse_punishment_debts` and do not mock `metrics.query`.

Replace `test_subscribe_and_show_today_for_current_chat_only` with:

```python
    async def test_subscribe_and_show_today_for_current_chat_only(self):
        repo = make_repository()
        today = today_msk().isoformat()
        repo.db.users = [
            User(id=DEFAULT_USER_ID, username="testuser", chat_ids=[CHAT_ID]),
            User(id=999, username="other", chat_ids=[CHAT_ID + 1]),
        ]
        repo.db.curse_punishments = [CursePunishment(id=1, coeff=5, title="отжиманий")]
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
        assert "10 отжиманий" in reply
        assert "@other" not in reply
```

Replace `test_done_with_id_updates_metric_and_timestamp` with:

```python
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
```

Replace `test_done_with_id_and_count_partially_offsets_words` with:

```python
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
```

Add imports at the top:

```python
from steward.data.models.curse import CurseParticipant, CursePunishment, CursePunishmentDebt
from steward.helpers.curse_debt import today_msk
```

and remove the old separate import if needed.

- [ ] **Step 2: Run updated handler tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_handler.py::TestCursePunishment -q
```

Expected: FAIL because command logic still queries metrics and updates participant offsets.

- [ ] **Step 3: Add report formatting helpers**

In `steward/helpers/curse_debt.py`, add:

```python
from dataclasses import dataclass


@dataclass
class CurseDebtReportEntry:
    user_id: int
    name: str
    items: list[tuple[str, int]]


def _display_name(username: str | None, user_id: int) -> str:
    return f"@{username}" if username else f"@{user_id}"


def _user_name(repo: Repository, user_id: int) -> str:
    user = next((u for u in repo.db.users if u.id == user_id), None)
    if user is None:
        return _display_name(None, user_id)
    return _display_name(user.username, user_id)


def _user_ids_in_chat(repo: Repository, chat_id: int) -> set[int]:
    return {user.id for user in repo.db.users if chat_id in user.chat_ids}


def build_curse_debt_report_entries(repo: Repository, chat_id: int) -> list[CurseDebtReportEntry]:
    user_ids_in_chat = _user_ids_in_chat(repo, chat_id)
    by_user_and_title: dict[int, dict[str, int]] = {}

    for debt in repo.db.curse_punishment_debts:
        if debt.punishment_count <= 0:
            continue
        if debt.user_id not in user_ids_in_chat:
            continue
        rule = _rule_by_id(repo, debt.rule_id)
        if rule is None:
            logger.warning(
                "curse debt report skipped missing rule_id=%s debt_id=%s user_id=%s",
                debt.rule_id,
                debt.id,
                debt.user_id,
            )
            continue
        user_items = by_user_and_title.setdefault(debt.user_id, {})
        user_items[rule.title] = user_items.get(rule.title, 0) + debt.punishment_count

    entries = [
        CurseDebtReportEntry(
            user_id=user_id,
            name=_user_name(repo, user_id),
            items=sorted(items.items()),
        )
        for user_id, items in by_user_and_title.items()
        if items
    ]
    entries.sort(key=lambda entry: entry.name.lower())
    return entries


def format_curse_debt_report(entries: list[CurseDebtReportEntry]) -> str:
    if not entries:
        return "Сегодня наказаний нет."

    lines = ["Наказания на сегодня:", ""]
    for index, entry in enumerate(entries):
        lines.append(f"`{entry.name}`")
        for title, count in entry.items:
            lines.append(f"{count} {title}")
        if index != len(entries) - 1:
            lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Add debt payment helper**

In `steward/helpers/curse_debt.py`, add:

```python
def find_user_debt(repo: Repository, user_id: int, rule_id: int) -> CursePunishmentDebt | None:
    return _find_debt(repo, user_id, rule_id)


def reduce_curse_debt(repo: Repository, user_id: int, rule_id: int, count: int | None) -> tuple[int, int]:
    debt = _find_debt(repo, user_id, rule_id)
    if debt is None or debt.punishment_count <= 0:
        return 0, 0

    before = debt.punishment_count
    paid = before if count is None else min(count, before)
    debt.punishment_count = before - paid
    if debt.punishment_count <= 0:
        repo.db.curse_punishment_debts.remove(debt)
    logger.info(
        "curse debt reduced user_id=%s rule_id=%s paid=%s before=%s after=%s",
        user_id,
        rule_id,
        paid,
        before,
        max(before - paid, 0),
    )
    return paid, max(before - paid, 0)
```

- [ ] **Step 5: Convert `CurseFeature` imports**

In `steward/features/curse.py`, replace old helper imports:

```python
from steward.helpers.curse_punishment import (
    build_punishment_today_entries,
    format_punishment_today_text,
    get_current_curse_count,
)
```

with:

```python
from steward.helpers.curse_debt import (
    accrue_curse_debt,
    apply_curse_interest_until,
    build_curse_debt_report_entries,
    format_curse_debt_report,
    reduce_curse_debt,
)
```

Also add:

```python
from datetime import datetime, timedelta, timezone
```

Do not add a direct dependency on the system local calendar here; use `today_msk()` from `steward.helpers.curse_debt`.

- [ ] **Step 6: Convert `/curse <n>` to accrue DB debts**

In `increment`, after metrics inc:

```python
        if accrue_curse_debt(self.repository, ctx.user_id, n, today_msk()):
            await self.repository.save()
```

- [ ] **Step 7: Convert `/curse punishment today`**

Replace body of `punishment_today`:

```python
        if apply_curse_interest_until(self.repository, today_msk()):
            await self.repository.save()
        entries = build_curse_debt_report_entries(self.repository, ctx.chat_id)
        await ctx.reply(format_curse_debt_report(entries))
```

- [ ] **Step 8: Convert `_done` to DB debt**

Inside `_done`, keep the subscription check and reset behavior for `/curse done` with no id.

For `punishment_id is None`, change the message to make the new semantics explicit:

```python
            debts = [
                debt for debt in self.repository.db.curse_punishment_debts
                if debt.user_id == user_id
            ]
            for debt in debts:
                self.repository.db.curse_punishment_debts.remove(debt)
            await self.curse_participants.save()
            await ctx.reply("Все наказания сброшены.")
            return
```

After finding `punishment`, replace all metric-query/effective-words logic with:

```python
        if count is not None and count <= 0:
            raise ValidationArgumentsError()

        paid, remaining = reduce_curse_debt(self.repository, user_id, punishment.id, count)
        if paid <= 0:
            await ctx.reply("Сейчас наказаний нет.")
            return

        labels = {
            "punishment_id": str(punishment.id),
            "punishment_title": punishment.title,
        }
        ctx.metrics.inc("bot_curse_punishment_done_total", labels, paid)
        await self.curse_participants.save()

        if remaining <= 0:
            await ctx.reply(
                f"Наказание засчитано: {paid} {punishment.title}. Долг закрыт."
            )
            return

        await ctx.reply(
            f"Засчитано: {paid} {punishment.title}. Осталось: {remaining} {punishment.title}."
        )
```

Do not require `count % coeff == 0` anymore. `count` is now direct punishment units, not curse-word-equivalent units.

- [ ] **Step 9: Run handler tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_handler.py -q
```

Expected: PASS after updating any assertions that still expect `done_words_offset`.

---

### Task 7: Add Rule Interest/Update Commands And Safe Removal

**Files:**
- Modify: `steward/features/curse.py`
- Test: `tests/test_curse_handler.py`

- [ ] **Step 1: Add failing command tests**

Append to `TestCursePunishment` in `tests/test_curse_handler.py`:

```python
    async def test_sets_punishment_interest_after_catchup(self):
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

        reply, ok = await invoke(CurseFeature, "/curse punishment interest 1 20.5", repo)

        assert ok
        assert "20.5" in reply
        assert repo.db.curse_punishments[0].interest_percent == 20.5
        assert repo.db.curse_punishment_debts[0].punishment_count == 111
        assert repo.db.curse_punishment_debts[0].last_interest_applied_date == today

    async def test_updates_punishment_coeff_for_future_accrual(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_punishments = [
            CursePunishment(id=1, coeff=10, title="приседаний", interest_percent=0.0)
        ]

        reply, ok = await invoke(CurseFeature, "/curse punishment coeff 1 15", repo)

        assert ok
        assert "15" in reply
        assert repo.db.curse_punishments[0].coeff == 15

    async def test_rejects_punishment_remove_when_debt_exists(self):
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

        reply, ok = await invoke(CurseFeature, "/curse punishment remove 1", repo)

        assert ok
        assert "долг" in reply.lower()
        assert len(repo.db.curse_punishments) == 1
```

Add `timedelta` to the existing import:

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 2: Run command tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_handler.py::TestCursePunishment::test_sets_punishment_interest_after_catchup tests/test_curse_handler.py::TestCursePunishment::test_updates_punishment_coeff_for_future_accrual tests/test_curse_handler.py::TestCursePunishment::test_rejects_punishment_remove_when_debt_exists -q
```

Expected: FAIL because commands and safe removal are not implemented.

- [ ] **Step 3: Show interest in punishment list**

In `show_punishments`, change the line format from:

```python
            lines.append(f"{p.id}. {p.coeff} -> {p.title}")
```

to:

```python
            lines.append(f"{p.id}. {p.coeff} -> {p.title} ({p.interest_percent}% в день)")
```

- [ ] **Step 4: Add rule update commands**

Add these subcommands after `add_punishment`:

```python
    @subcommand("punishment coeff <id:int> <coeff:int>", description="Изменить коэффициент", admin=True)
    async def update_punishment_coeff(self, ctx: FeatureContext, id: int, coeff: int):
        if coeff <= 0:
            raise ValidationArgumentsError()
        punishment = self.curse_punishments.find_by(id=id)
        if punishment is None:
            await ctx.reply("Наказание не найдено.")
            return
        old = punishment.coeff
        punishment.coeff = coeff
        await self.curse_punishments.save()
        logger.info(
            "curse punishment coeff changed rule_id=%s title=%r old=%s new=%s admin_user_id=%s",
            punishment.id,
            punishment.title,
            old,
            coeff,
            ctx.user_id,
        )
        await ctx.reply(f"Коэффициент наказания {id} изменён: {old} -> {coeff}.")

    @subcommand("punishment interest <id:int> <percent:float>", description="Изменить процент", admin=True)
    async def update_punishment_interest(self, ctx: FeatureContext, id: int, percent: float):
        if percent < 0.0:
            raise ValidationArgumentsError()
        punishment = self.curse_punishments.find_by(id=id)
        if punishment is None:
            await ctx.reply("Наказание не найдено.")
            return
        if apply_curse_interest_until(self.repository, today_msk()):
            await self.repository.save()
        old = punishment.interest_percent
        punishment.interest_percent = percent
        await self.curse_punishments.save()
        logger.info(
            "curse punishment interest changed rule_id=%s title=%r old=%s new=%s admin_user_id=%s",
            punishment.id,
            punishment.title,
            old,
            percent,
            ctx.user_id,
        )
        await ctx.reply(f"Процент наказания {id} изменён: {old}% -> {percent}%.")

    @subcommand("punishment rename <id:int> <title:rest>", description="Переименовать наказание", admin=True)
    async def rename_punishment(self, ctx: FeatureContext, id: int, title: str):
        title = title.strip()
        if not title:
            raise ValidationArgumentsError()
        punishment = self.curse_punishments.find_by(id=id)
        if punishment is None:
            await ctx.reply("Наказание не найдено.")
            return
        old = punishment.title
        punishment.title = title
        await self.curse_punishments.save()
        logger.info(
            "curse punishment title changed rule_id=%s old=%r new=%r admin_user_id=%s",
            punishment.id,
            old,
            title,
            ctx.user_id,
        )
        await ctx.reply(f"Наказание {id} переименовано: {old} -> {title}.")
```

At the top of `steward/features/curse.py`, add:

```python
import logging
```

and near `_MSK` add:

```python
logger = logging.getLogger(__name__)
```

- [ ] **Step 5: Make remove safe**

In `remove_punishment`, before removing:

```python
        has_debt = any(
            debt.rule_id == id and debt.punishment_count > 0
            for debt in self.repository.db.curse_punishment_debts
        )
        if has_debt:
            await ctx.reply("Нельзя удалить наказание: по нему есть открытый долг.")
            return
```

After successful removal, add:

```python
        logger.info(
            "curse punishment removed rule_id=%s title=%r admin_user_id=%s",
            p.id,
            p.title,
            ctx.user_id,
        )
```

- [ ] **Step 6: Run punishment command tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_handler.py::TestCursePunishment -q
```

Expected: PASS.

---

### Task 8: Run Interest In Daily Delayed Action

**Files:**
- Modify: `steward/delayed_action/curse_punishment_digest.py`
- Test: `tests/test_curse_debt.py` or add direct test in `tests/test_curse_handler.py`

- [ ] **Step 1: Add direct delayed action test**

Append to `tests/test_curse_debt.py`:

```python
from unittest.mock import MagicMock

from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.curse_punishment_digest import CursePunishmentDigestDelayedAction
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.helpers.curse_debt import today_msk


async def test_digest_action_applies_interest_before_reporting():
    repo = make_repository()
    repo.db.users = []
    repo.db.curse_punishments = [
        CursePunishment(id=1, coeff=10, title="приседаний", interest_percent=10.0)
    ]
    today_date = today_msk()
    yesterday = (today_date - timedelta(days=1)).isoformat()
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
        generator=ConstantGenerator(start=datetime.now(timezone.utc), period=timedelta(days=1))
    )
    context = DelayedActionContext(repo, MagicMock(), MagicMock(), MagicMock())

    await action.execute(context)

    assert repo.db.curse_punishment_debts[0].punishment_count == 110
    assert repo.db.curse_punishment_debts[0].last_interest_applied_date == today_date.isoformat()
```

- [ ] **Step 2: Run delayed action test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_debt.py::test_digest_action_applies_interest_before_reporting -q
```

Expected: FAIL because digest action does not apply interest.

- [ ] **Step 3: Update digest action**

In `steward/delayed_action/curse_punishment_digest.py`, import:

```python
from datetime import date
from steward.helpers.curse_debt import (
    apply_curse_interest_until,
    build_curse_debt_report_entries,
    format_curse_debt_report,
    today_msk,
)
```

Remove imports from `steward.helpers.curse_punishment`.

At the start of `execute`, add:

```python
        if apply_curse_interest_until(context.repository, today_msk()):
            await context.repository.save()
```

Replace report building:

```python
            entries = await build_punishment_today_entries(
                context.repository,
                context.metrics,
                chat_id,
            )
            if not entries:
                continue

            text = format_punishment_today_text(context.repository, entries)
```

with:

```python
            entries = build_curse_debt_report_entries(context.repository, chat_id)
            if not entries:
                continue

            text = format_curse_debt_report(entries)
```

- [ ] **Step 4: Run delayed action and startup tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_debt.py tests/test_startup.py -q
```

Expected: PASS.

---

### Task 9: Update Existing Tests And Remove Metric Debt Dependencies

**Files:**
- Modify: `tests/test_curse_handler.py`
- Modify: `tests/test_curse_metric_handler.py`
- Modify: `steward/helpers/curse_punishment.py` if it becomes unused

- [ ] **Step 1: Search for old helper usages**

Run:

```bash
rg "get_current_curse_count|build_punishment_today_entries|format_punishment_today_text|done_words_offset|metrics.query" tests steward -g '*.py'
```

Expected: remaining usages are limited to legacy metric materialization inside `steward/helpers/curse_debt.py`, model compatibility fields, or code that is updated by the next steps in this task.

- [ ] **Step 2: Update old done tests**

In `tests/test_curse_handler.py`, ensure these old assertions are gone:

```python
assert participant.done_words_offset == 1
assert participant.done_words_offset == 0
metrics.query = AsyncMock(...)
```

The replacement assertions must check `repo.db.curse_punishment_debts`.

- [ ] **Step 3: Keep legacy helper only for backfill**

If `steward/helpers/curse_punishment.py` is still imported only by `steward/helpers/curse_debt.py`, keep it for now and add a short module comment at the top:

```python
"""Legacy metric-based helpers used only for one-time curse debt backfill."""
```

Do not delete it in this task; deleting it would make rollback/backfill harder.

- [ ] **Step 4: Run curse-focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_repository.py tests/test_curse_debt.py tests/test_curse_metric_handler.py tests/test_curse_handler.py -q
```

Expected: PASS.

---

### Task 10: Final Verification

**Files:**
- No code changes unless verification reveals a defect.

- [ ] **Step 1: Compile changed modules**

Run:

```bash
.venv/bin/python -m py_compile steward/data/models/curse.py steward/data/models/db.py steward/helpers/curse_debt.py steward/features/curse.py steward/features/curse_metric.py steward/delayed_action/curse_punishment_digest.py steward/bot/bot.py
```

Expected: command exits with code 0.

- [ ] **Step 2: Run startup tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_startup.py -q
```

Expected: PASS.

- [ ] **Step 3: Run focused curse suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_curse_repository.py tests/test_curse_debt.py tests/test_curse_metric_handler.py tests/test_curse_handler.py -q
```

Expected: PASS.

- [ ] **Step 4: Run main test suite**

Run:

```bash
.venv/bin/python -m pytest tests -q
```

Expected: PASS.

- [ ] **Step 5: Check full pytest collection**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: This may still fail on the existing unrelated `junk/google_sheet_test.py` dependency issue (`google_auth_oauthlib` missing). If it fails only there, record it as an existing unrelated blocker and do not modify `junk/`.

- [ ] **Step 6: Inspect git diff**

Run:

```bash
git diff -- steward/data/models/curse.py steward/data/models/db.py steward/data/repository.py steward/helpers/curse_debt.py steward/helpers/curse_punishment.py steward/features/curse.py steward/features/curse_metric.py steward/delayed_action/curse_punishment_digest.py steward/bot/bot.py tests/test_curse_repository.py tests/test_curse_debt.py tests/test_curse_metric_handler.py tests/test_curse_handler.py tests/test_startup.py
```

Expected: Diff shows only scoped curse debt/interest changes.

---

## Logging Requirements

Use `logging.getLogger(__name__)` in files that mutate rules/debts.

Required `INFO` logs:

- Interest applied per debt/day:
  - `debt_id`
  - `user_id`
  - `rule_id`
  - `title`
  - applied date
  - percent
  - before count
  - after count
- Interest catch-up/backfill summary at startup:
  - backfill completed
  - user id and effective words for each backfilled participant
- Rule changes:
  - coeff old/new
  - interest percent old/new
  - title old/new
  - admin user id
- Rule removal:
  - rule id
  - title
  - admin user id
- Debt reduction through `/curse done`:
  - user id
  - rule id
  - paid count
  - before count
  - after count

Required `WARNING` logs:

- Interest skipped because debt references a missing rule.
- Accrual skipped because a rule has invalid `coeff`.

Use only `DEBUG` logs, not `INFO`, for automatic debt accrual from normal curse messages. Do not log every detected curse word at info level.

---

## Behavioral Notes

- `count` in `/curse done <id> <count>` becomes direct punishment units, not “number of curse words multiplied by coeff”.
- Existing metrics remain:
  - `bot_curse_words_total` for graphs.
  - `bot_curse_punishment_done_total` for completed punishment analytics.
- DB debt is authoritative after startup initialization.
- `last_interest_applied_date` is a technical cursor, not a user-facing “debt date”.
- New debts are created with `last_interest_applied_date = today`, so interest does not apply on the same day.
- If a daily delayed action is skipped, startup or `/curse punishment today` catches interest up later.
- Before changing `interest_percent`, run catch-up with the old percent first.
- Do not introduce per-day debt objects in this implementation.

---

## Self-Review Checklist

- Spec coverage:
  - DB debt source of truth: Tasks 1, 2, 5, 6.
  - Metrics retained for graphs: Tasks 5 and 6.
  - Interest catch-up: Tasks 3, 4, 7, 8.
  - Startup and delayed action catch-up: Tasks 4 and 8.
  - `/curse punishment today` catch-up: Task 6.
  - Logging: Tasks 2, 3, 4, 7 plus Logging Requirements section.
  - Safe rule removal: Task 7.
- Placeholder scan:
  - The plan contains concrete test code, implementation snippets, and exact verification commands for every task.
- Type consistency:
  - Model uses `CursePunishmentDebt`.
  - DB field uses `curse_punishment_debts`.
  - Rule id field in debt is `rule_id`, matching `CursePunishment.id`.
  - Date cursor is `last_interest_applied_date`.
