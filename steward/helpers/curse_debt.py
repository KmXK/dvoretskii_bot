import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil, isfinite
from random import choices
from zoneinfo import ZoneInfo

from steward.data.models.curse import CursePunishment, CursePunishmentDay, CursePunishmentDebt
from steward.data.repository import Repository
from steward.helpers.curse_punishment import get_current_curse_count


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


def _parse_date_key(value: str) -> date:
    return date.fromisoformat(value)


def _rule_by_id(repo: Repository, rule_id: int):
    return next((rule for rule in repo.db.curse_punishments if rule.id == rule_id), None)


def _find_punishment_day(repo: Repository, today: date) -> CursePunishmentDay | None:
    today_value = date_key(today)
    return next((day for day in repo.db.curse_punishment_days if day.date == today_value), None)


def _weighted_punishment_candidates(repo: Repository) -> list[CursePunishment]:
    candidates = []
    for rule in repo.db.curse_punishments:
        if not isfinite(rule.selection_weight) or rule.selection_weight <= 0:
            continue
        candidates.append(rule)
    return candidates


def select_curse_punishment_for_day(
    repo: Repository,
    today: date,
) -> tuple[CursePunishment | None, bool]:
    day = _find_punishment_day(repo, today)
    if day is not None:
        selected = _rule_by_id(repo, day.rule_id)
        if selected is not None:
            return selected, False
        logger.warning(
            "curse punishment day references missing rule_id=%s date=%s",
            day.rule_id,
            day.date,
        )

    candidates = _weighted_punishment_candidates(repo)
    if not candidates:
        return None, False

    selected = choices(
        candidates,
        weights=[rule.selection_weight for rule in candidates],
        k=1,
    )[0]
    today_value = date_key(today)
    if day is None:
        repo.db.curse_punishment_days.append(
            CursePunishmentDay(date=today_value, rule_id=selected.id)
        )
    else:
        day.rule_id = selected.id
    logger.info(
        "curse punishment day selected date=%s rule_id=%s title=%r weight=%s",
        today_value,
        selected.id,
        selected.title,
        selected.selection_weight,
    )
    return selected, True


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

    rule, day_changed = select_curse_punishment_for_day(repo, today)
    if rule is None:
        return day_changed
    return _accrue_curse_debt_for_rule(repo, user_id, curse_count, today, rule) or day_changed


def _accrue_curse_debt_for_rule(
    repo: Repository,
    user_id: int,
    curse_count: int,
    today: date,
    rule: CursePunishment,
) -> bool:
    today_value = date_key(today)
    if rule.coeff <= 0:
        logger.warning(
            "curse debt accrual skipped invalid rule_id=%s coeff=%s",
            rule.id,
            rule.coeff,
        )
        return False
    delta = curse_count * rule.coeff
    debt = _find_debt(repo, user_id, rule.id)
    if debt is None:
        repo.db.curse_punishment_debts.append(
            CursePunishmentDebt(
                id=_next_debt_id(repo),
                user_id=user_id,
                rule_id=rule.id,
                punishment_count=delta,
                last_interest_applied_date=today_value,
            )
        )
    else:
        debt.punishment_count += delta
    logger.debug(
        "curse debt accrued user_id=%s rule_id=%s curse_count=%s delta=%s",
        user_id,
        rule.id,
        curse_count,
        delta,
    )
    return True


def accrue_legacy_curse_debt_for_all_rules(
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
    for rule in repo.db.curse_punishments:
        if _accrue_curse_debt_for_rule(repo, user_id, curse_count, today, rule):
            changed = True
    return changed


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


async def initialize_curse_debts(repo: Repository, metrics, today: date) -> bool:
    changed = apply_curse_interest_until(repo, today)

    if repo.db.curse_debts_backfilled:
        return changed

    backfill_items: list[tuple[int, int, datetime | None]] = []
    for participant in repo.db.curse_participants:
        since = participant.last_done_at or participant.subscribed_at
        try:
            raw_count = await get_current_curse_count(
                metrics,
                participant.user_id,
                since,
                strict=True,
            )
        except Exception:
            logger.warning("curse debt backfill postponed: metrics query failed", exc_info=True)
            return changed
        effective_words = max(raw_count - (participant.done_words_offset or 0), 0)
        if effective_words <= 0:
            continue
        backfill_items.append((participant.user_id, effective_words, since))

    for user_id, effective_words, since in backfill_items:
        if accrue_legacy_curse_debt_for_all_rules(repo, user_id, effective_words, today):
            changed = True
            logger.info(
                "curse debt backfilled user_id=%s words=%s since=%s",
                user_id,
                effective_words,
                since,
            )

    repo.db.curse_debts_backfilled = True
    changed = True
    logger.info("curse debt backfill completed")
    return changed


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
