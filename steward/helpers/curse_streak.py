from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html import escape as html_escape
from zoneinfo import ZoneInfo

from steward.data.models.curse import CurseStreak


_MSK = ZoneInfo("Europe/Minsk")


@dataclass(frozen=True)
class CurseStreakOutcome:
    user_id: int
    days: int
    curses: int
    reset: bool


def _participant_ids(repository) -> set[int]:
    return {participant.user_id for participant in repository.db.curse_participants}


def _record(repository, user_id: int) -> CurseStreak | None:
    return next((item for item in repository.db.curse_streaks if item.user_id == user_id), None)


def _ensure_record(repository, user_id: int) -> CurseStreak:
    current = _record(repository, user_id)
    if current is not None:
        return current
    current = CurseStreak(user_id=user_id)
    repository.db.curse_streaks.append(current)
    return current


def _normalized_hourly_counts(item: CurseStreak) -> list[int]:
    counts = list(item.hourly_curse_counts[:24])
    counts.extend([0] * (24 - len(counts)))
    return counts


def record_curses(
    repository,
    user_id: int,
    count: int,
    day: date,
    hour: int | None = None,
) -> bool:
    """Записать маты для стрика. Незарегистрированных участников не трогаем."""
    if count <= 0 or user_id not in _participant_ids(repository):
        return False
    item = _ensure_record(repository, user_id)
    key = day.isoformat()
    previous_count = (
        item.curses_on_last_curse_date
        if item.last_curse_date == key
        else 0
    )
    if item.last_curse_date == key:
        item.curses_on_last_curse_date += count
    else:
        item.last_curse_date = key
        item.curses_on_last_curse_date = count

    current_hour = datetime.now(_MSK).hour if hour is None else hour
    if item.hourly_curse_date != key:
        item.hourly_curse_date = key
        item.hourly_curse_counts = [0] * 24
        if 0 <= current_hour < 24:
            item.hourly_curse_counts[current_hour] = previous_count
    else:
        item.hourly_curse_counts = _normalized_hourly_counts(item)
    if 0 <= current_hour < 24:
        item.hourly_curse_counts[current_hour] += count

    item.days = 0
    return True


def finalize_curse_streaks(repository, completed_day: date) -> list[CurseStreakOutcome]:
    """Закрыть сутки для всех подписчиков. Повторный вызов идемпотентен."""
    result: list[CurseStreakOutcome] = []
    for user_id in sorted(_participant_ids(repository)):
        item = _ensure_record(repository, user_id)
        if item.last_finalized_date:
            last_finalized = date.fromisoformat(item.last_finalized_date)
            if last_finalized >= completed_day:
                continue
            elapsed = (completed_day - last_finalized).days
        else:
            elapsed = 1

        last_curse = date.fromisoformat(item.last_curse_date) if item.last_curse_date else None
        curses = item.curses_on_last_curse_date if last_curse == completed_day else 0
        reset = curses > 0
        if last_curse is not None and (
            not item.last_finalized_date or last_curse > date.fromisoformat(item.last_finalized_date)
        ) and last_curse <= completed_day:
            item.days = (completed_day - last_curse).days
        else:
            item.days += elapsed
        item.last_finalized_date = completed_day.isoformat()
        result.append(CurseStreakOutcome(user_id, item.days, curses, reset))
    return result


def _name(repository, user_id: int) -> str:
    user = next((user for user in repository.db.users if user.id == user_id), None)
    raw = f"@\u200b{user.username}" if user and user.username else f"@\u200b{user_id}"
    return f"<code>{html_escape(raw)}</code>"


def participant_ids_in_chat(repository, chat_id: int) -> list[int]:
    return sorted(
        {
            participant.user_id
            for participant in repository.db.curse_participants
            if chat_id in participant.source_chat_ids
        }
    )


def curse_report_chat_ids(repository) -> list[int]:
    return sorted(
        {
            chat_id
            for participant in repository.db.curse_participants
            for chat_id in participant.source_chat_ids
        }
    )


def hourly_curse_counts(repository, user_id: int, day: date) -> list[int]:
    item = _record(repository, user_id)
    if item is None:
        return [0] * 24
    day_key = day.isoformat()
    if item.hourly_curse_date != day_key:
        counts = [0] * 24
        if item.last_curse_date == day_key:
            counts[23] = item.curses_on_last_curse_date
        return counts
    return _normalized_hourly_counts(item)


def _days(value: int) -> str:
    mod100 = value % 100
    mod10 = value % 10
    word = "день" if mod10 == 1 and mod100 != 11 else (
        "дня" if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14 else "дней"
    )
    return f"{value} {word}"


def _curses(value: int) -> str:
    mod100 = value % 100
    mod10 = value % 10
    word = "мат" if mod10 == 1 and mod100 != 11 else (
        "мата" if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14 else "матов"
    )
    return f"{value} {word}"


def format_curse_streak_forecast(repository, chat_id: int, today: date) -> str:
    lines = ["🔥 Стрик без матов — прогноз:", ""]
    for user_id in participant_ids_in_chat(repository, chat_id):
        item = _record(repository, user_id)
        current = item.days if item else 0
        curses = (
            item.curses_on_last_curse_date
            if item and item.last_curse_date == today.isoformat()
            else 0
        )
        if curses:
            lines.append(
                f"{_name(repository, user_id)}: сегодня {_curses(curses)}, "
                "стрик сброшен"
            )
        else:
            lines.append(
                f"{_name(repository, user_id)}: сейчас {_days(current)}, "
                f"в полночь будет {_days(current + 1)}"
            )
    return "\n".join(lines) if len(lines) > 2 else ""


def format_curse_streak_outcome(
    repository,
    chat_id: int,
    outcomes: list[CurseStreakOutcome],
) -> str:
    by_user = {item.user_id: item for item in outcomes}
    lines = ["🔥 Стрик без матов — итог:", ""]
    for user_id in participant_ids_in_chat(repository, chat_id):
        item = by_user.get(user_id)
        if item is None:
            continue
        if item.reset:
            lines.append(
                f"{_name(repository, user_id)}: стрик сброшен — "
                f"{_curses(item.curses)} за сутки"
            )
        else:
            lines.append(
                f"{_name(repository, user_id)}: {_days(item.days)} без матов "
                f"(+1), за сутки 0"
            )
    return "\n".join(lines) if len(lines) > 2 else ""
