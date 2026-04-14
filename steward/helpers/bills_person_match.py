"""Person matching for /bills with ranked disambiguation.

Replaces the flat _match_name from the old bills_handler.
Ranks candidates using:
  - Exact vs fuzzy name match (display_name, aliases, telegram_username, stand_name, stand_aliases)
  - Recent co-activity in the same chat (chat_last_seen)
  - Shared Telegram chats with the caller
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steward.data.models.bill_v2 import BillPerson
    from steward.data.models.user import User


def _names_for_person(
    p: "BillPerson",
    users_by_id: dict[int, "User"],
) -> list[str]:
    """Return all lowercased name variants for a BillPerson."""
    ns: list[str] = [p.display_name.lower()]
    if p.telegram_username:
        ns.append(p.telegram_username.lower())
    ns.extend(a.lower() for a in p.aliases)
    if p.telegram_id:
        user = users_by_id.get(p.telegram_id)
        if user:
            if user.stand_name:
                ns.append(user.stand_name.lower())
            ns.extend(a.lower() for a in user.stand_aliases)
    return ns


def _decay_bonus(last_seen_iso: str, half_life_days: float = 30.0) -> float:
    """Exponential decay bonus [0, 1] based on how recently a person was seen."""
    try:
        last = datetime.fromisoformat(last_seen_iso)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.0
    days_ago = (datetime.now(timezone.utc) - last).total_seconds() / 86400.0
    return math.exp(-days_ago * math.log(2) / half_life_days)


def rank_person_matches(
    name: str,
    bill_persons: list["BillPerson"],
    users_by_id: dict[int, "User"],
    caller_telegram_id: int | None = None,
    origin_chat_id: int | None = None,
) -> list[tuple["BillPerson", float]]:
    """Return a sorted list of (BillPerson, score) — highest score first.

    Scoring:
      base 1000 for exact name match, 500 for fuzzy (first-word / substring).
      +200 * decay_bonus if person was recently seen in origin_chat_id.
      +150 if both person and caller share origin_chat_id via User.chat_ids.
      Items with score < 300 are excluded.
    """
    name_lower = name.strip().lower().lstrip("@")
    if not name_lower:
        return []

    first_word = name_lower.split()[0]
    caller_user = None
    if caller_telegram_id:
        caller_user = users_by_id.get(caller_telegram_id)

    results: list[tuple["BillPerson", float]] = []
    for p in bill_persons:
        names = _names_for_person(p, users_by_id)

        # Base score
        if name_lower in names:
            base = 1000.0
        else:
            fuzzy = any(
                (first_word and n.split()[0] == first_word) or (name_lower in n)
                for n in names
            )
            if fuzzy:
                base = 500.0
            else:
                continue

        bonus = 0.0

        # Recent co-activity in same chat
        if origin_chat_id and str(origin_chat_id) in p.chat_last_seen:
            bonus += 200.0 * _decay_bonus(p.chat_last_seen[str(origin_chat_id)])

        # Shared chat membership
        if origin_chat_id and p.telegram_id and caller_user:
            person_user = users_by_id.get(p.telegram_id)
            if person_user and origin_chat_id in person_user.chat_ids and origin_chat_id in caller_user.chat_ids:
                bonus += 150.0

        score = base + bonus
        if score >= 300:
            results.append((p, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def match_name(
    name: str,
    bill_persons: list["BillPerson"],
    users_by_id: dict[int, "User"],
    caller_telegram_id: int | None = None,
    origin_chat_id: int | None = None,
) -> tuple["BillPerson | None", list["BillPerson"]]:
    """Resolve a name to a BillPerson. Returns (exact, candidates).

    Returns (person, []) if confident match (score gap ≥ 300, top score ≥ 800).
    Returns (None, [top candidates]) if ambiguous.
    Returns (None, []) if no match.
    """
    ranked = rank_person_matches(
        name, bill_persons, users_by_id, caller_telegram_id, origin_chat_id
    )
    if not ranked:
        return None, []

    top_person, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    # Auto-match if clearly the best candidate
    if top_score >= 800 and (top_score - second_score) >= 300:
        return top_person, []

    # Return top candidates (up to 5) for user disambiguation
    candidates = [p for p, _ in ranked[:5]]
    return None, candidates


def update_chat_last_seen(
    person: "BillPerson",
    chat_id: int,
) -> None:
    """Record that this person participated in a bill activity in chat_id."""
    person.chat_last_seen[str(chat_id)] = datetime.now().isoformat()
