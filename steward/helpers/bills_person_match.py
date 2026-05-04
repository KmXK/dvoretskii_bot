"""Person matching for /bills with ranked disambiguation.

Replaces the flat _match_name from the old bills_handler.
Ranks candidates using:
  - Chat-scoped nicknames (highest priority — the explicit user-set alias inside chat)
  - Exact vs fuzzy name match (display_name, aliases, telegram_username, stand_name, stand_aliases)
  - Recent co-activity in the same chat (chat_last_seen)
  - Shared Telegram chats with the caller
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steward.data.models.bill_v2 import BillPerson
    from steward.data.models.chat import Chat
    from steward.data.models.user import User


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _names_for_person(
    p: "BillPerson",
    users_by_id: dict[int, "User"],
) -> list[str]:
    """Return all lowercased name variants for a BillPerson (excluding chat-scoped nicks)."""
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
    *,
    chat_nicknames_index: dict[int, dict[str, str]] | None = None,
    scoped_chat_ids: list[int] | None = None,
) -> list[tuple["BillPerson", float]]:
    """Return a sorted list of (BillPerson, score) — highest score first.

    Scoring (in order of priority):
      base 2000 if a chat-scoped nick exact-matches in origin_chat_id
      base 1500 if a chat-scoped nick exact-matches in any of `scoped_chat_ids`
      base 1000 for exact name match (display_name/username/aliases/stand_name/stand_aliases)
      base 500 for fuzzy (first-word / substring) on those names
      +200 * decay_bonus if person was recently seen in origin_chat_id
      +150 if both person and caller share origin_chat_id via User.chat_ids

    `scoped_chat_ids` is used in DM mode to broaden the chat-nick lookup across
    the caller's accessible chats (User.chat_ids).
    """
    name_lower = _norm(name).lstrip("@")
    if not name_lower:
        return []

    by_id = {p.id: p for p in bill_persons}

    # Chat-scoped nick lookup
    nick_hits: dict[str, float] = {}  # person_id -> base score from nick match
    nick_chat_match: dict[str, int] = {}  # person_id -> chat_id where nick matched
    if chat_nicknames_index:
        if origin_chat_id is not None:
            chat_map = chat_nicknames_index.get(origin_chat_id, {})
            pid = chat_map.get(name_lower)
            if pid:
                nick_hits[pid] = max(nick_hits.get(pid, 0.0), 2000.0)
                nick_chat_match[pid] = origin_chat_id
        if scoped_chat_ids:
            for cid in scoped_chat_ids:
                if cid == origin_chat_id:
                    continue
                pid = chat_nicknames_index.get(cid, {}).get(name_lower)
                if pid and pid not in nick_hits:
                    nick_hits[pid] = max(nick_hits.get(pid, 0.0), 1500.0)
                    nick_chat_match[pid] = cid

    first_word = name_lower.split()[0] if name_lower else ""
    caller_user = None
    if caller_telegram_id:
        caller_user = users_by_id.get(caller_telegram_id)

    results: list[tuple["BillPerson", float]] = []
    seen_pids: set[str] = set()

    # Persons with a chat-nick match — guaranteed inclusion
    for pid, base in nick_hits.items():
        p = by_id.get(pid)
        if not p:
            continue
        bonus = 0.0
        if origin_chat_id and str(origin_chat_id) in p.chat_last_seen:
            bonus += 200.0 * _decay_bonus(p.chat_last_seen[str(origin_chat_id)])
        results.append((p, base + bonus))
        seen_pids.add(pid)

    # Persons matched by global name fields
    for p in bill_persons:
        if p.id in seen_pids:
            continue
        names = _names_for_person(p, users_by_id)
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
        if origin_chat_id and str(origin_chat_id) in p.chat_last_seen:
            bonus += 200.0 * _decay_bonus(p.chat_last_seen[str(origin_chat_id)])
        if origin_chat_id and p.telegram_id and caller_user:
            person_user = users_by_id.get(p.telegram_id)
            if (
                person_user
                and origin_chat_id in person_user.chat_ids
                and origin_chat_id in caller_user.chat_ids
            ):
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
    *,
    chat_nicknames_index: dict[int, dict[str, str]] | None = None,
    scoped_chat_ids: list[int] | None = None,
) -> tuple["BillPerson | None", list["BillPerson"]]:
    """Resolve a name to a BillPerson. Returns (exact, candidates).

    Returns (person, []) if confident match (score gap ≥ 300, top score ≥ 800).
    Returns (None, [top candidates]) if ambiguous.
    Returns (None, []) if no match.
    """
    ranked = rank_person_matches(
        name,
        bill_persons,
        users_by_id,
        caller_telegram_id,
        origin_chat_id,
        chat_nicknames_index=chat_nicknames_index,
        scoped_chat_ids=scoped_chat_ids,
    )
    if not ranked:
        return None, []

    top_person, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    if top_score >= 800 and (top_score - second_score) >= 300:
        return top_person, []

    candidates = [p for p, _ in ranked[:5]]
    return None, candidates


def update_chat_last_seen(
    person: "BillPerson",
    chat_id: int,
) -> None:
    """Record that this person participated in a bill activity in chat_id."""
    person.chat_last_seen[str(chat_id)] = datetime.now().isoformat()


# Russian declension stems for common forms — matches the chat name when the user
# inflects it ("из джунглей" → "Джунгли", "с Дорой" → "Дора"). We strip the most
# common suffixes greedily, then compare prefixes case-insensitively.
_RU_SUFFIXES = (
    "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
    "ой", "ей", "ою", "ею", "ом", "ем", "ах", "ях", "ов", "ев", "ей",
    "ы", "и", "у", "ю", "е", "ё", "а", "я", "о",
)


def _stem(s: str) -> str:
    s = _norm(s)
    if len(s) < 4:
        return s
    for suf in _RU_SUFFIXES:
        if s.endswith(suf) and len(s) - len(suf) >= 3:
            return s[: -len(suf)]
    return s


_CHAT_REF_RE = re.compile(
    r"(?:^|[^\w\-])(?:из|с|со|в|во|на|по|у|про|от|для)\s+([A-Za-zА-Яа-яЁё][\w\-]{2,})",
    re.IGNORECASE,
)


def detect_chat_references(text: str, chats: list["Chat"]) -> list[tuple[str, "Chat"]]:
    """Find chat references in free-form text. Returns a list of (matched_word, Chat).

    Matches words after Russian prepositions (из/с/в/...) against chat titles
    and aliases via prefix-based stemming. Designed for DM scenarios where the
    user references a group chat by name ("из джунглей лёша заплатил").
    """
    if not text or not chats:
        return []

    chat_keys: list[tuple[str, "Chat"]] = []
    for c in chats:
        for n in [c.name, *(c.aliases or [])]:
            stem = _stem(n)
            if stem:
                chat_keys.append((stem, c))

    found: list[tuple[str, "Chat"]] = []
    seen_chats: set[int] = set()
    for m in _CHAT_REF_RE.finditer(text):
        word = m.group(1)
        wstem = _stem(word)
        if not wstem:
            continue
        for stem, chat in chat_keys:
            if (
                stem == wstem
                or (len(wstem) >= 4 and stem.startswith(wstem))
                or (len(stem) >= 4 and wstem.startswith(stem))
            ):
                if chat.id not in seen_chats:
                    found.append((word, chat))
                    seen_chats.add(chat.id)
                break
    return found


def fuzzy_score_telegram_candidate(
    query: str,
    user: "User",
    person: "BillPerson | None" = None,
) -> float:
    """Score a Telegram User as a candidate for binding to `query` name.

    Used by the resolve picker (`bills:resolve`) to rank chat members. Returns
    a [0, 1000] score; >= 700 means very likely a match, < 200 means unlikely.
    """
    q = _norm(query).lstrip("@")
    if not q:
        return 0.0

    candidates: list[str] = []
    if person:
        candidates.append(_norm(person.display_name))
        if person.telegram_username:
            candidates.append(_norm(person.telegram_username))
        candidates.extend(_norm(a) for a in person.aliases)
    if user.username:
        candidates.append(_norm(user.username))
    if getattr(user, "stand_name", None):
        candidates.append(_norm(user.stand_name))
    candidates.extend(_norm(a) for a in getattr(user, "stand_aliases", []) or [])

    candidates = [c for c in candidates if c]
    if not candidates:
        return 0.0

    if any(c == q for c in candidates):
        return 1000.0

    qstem = _stem(q)
    for c in candidates:
        cstem = _stem(c)
        if cstem and qstem and (cstem == qstem or cstem.startswith(qstem) or qstem.startswith(cstem)):
            return 800.0

    qfirst = q.split()[0] if q else ""
    for c in candidates:
        if qfirst and c.split()[0] == qfirst:
            return 600.0
        if q in c:
            return 400.0
    return 0.0
