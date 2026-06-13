"""Shared bill-collection pipeline (positions + participants, no distribution).

Used by both the chat wizard (`session.py`) and the web create flow
(`api/server.py`). Runs the slim `bill_collect` prompt over accumulated context
items, extracts positions and the guest list, and resolves names against the bill
persons directory. Distribution by person is NOT done here — it happens on the web
board.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from steward.helpers.ai import OpenRouterModel, get_prompt, make_openrouter_query
from steward.helpers.bills_person_match import match_name

from . import parse

logger = logging.getLogger(__name__)


def _bill_collect_prompt() -> str:
    return get_prompt("bill_collect")


@dataclass
class CollectResult:
    currency: str = "BYN"
    item_rows: list[dict] = field(default_factory=list)
    participant_names: list[str] = field(default_factory=list)
    new_person_names: list[str] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    resolved_map: dict[str, str] = field(default_factory=dict)
    resolve_queue: list[tuple[str, list]] = field(default_factory=list)


# -- directory helpers (repo-based, no Feature dependency) --

def chat_persons_for(repo, caller_tid: int, origin_chat_id: int | None) -> list:
    """Bill persons reachable from the caller (mirrors BillsFeature._chat_persons)."""
    author = next((u for u in repo.db.users if u.id == caller_tid), None)
    if not author:
        return [p for p in repo.db.bill_persons if p.telegram_id]
    users_map = {u.id: u for u in repo.db.users}
    is_dm = origin_chat_id is None or origin_chat_id == caller_tid
    scope = set(author.chat_ids) if is_dm else {origin_chat_id}
    return [
        p for p in repo.db.bill_persons
        if p.telegram_id and (u := users_map.get(p.telegram_id)) and set(u.chat_ids) & scope
    ]


def match_kwargs_for(repo, caller_tid: int) -> dict:
    """Kwargs for match_name (mirrors BillsFeature._match_kwargs)."""
    author = next((u for u in repo.db.users if u.id == caller_tid), None)
    scoped = list(getattr(author, "chat_ids", []) or []) if author else []
    return {
        "chat_nicknames_index": repo.chat_nicknames_index(),
        "scoped_chat_ids": scoped,
    }


def build_directory_block(
    repo, caller_tid: int, origin_chat_id: int | None, chat_persons: list,
) -> str:
    """Build the persons directory (+ known chats block in DM) for the AI prompt.

    Generalised from session._build_directory_block to take `repo` instead of a
    Feature so the web flow can reuse it.
    """
    is_dm = origin_chat_id is None or origin_chat_id == caller_tid

    nicks_for_persons: dict[str, list[str]] = {}
    for n in repo.db.chat_nicknames:
        if is_dm or n.chat_id == origin_chat_id:
            nicks_for_persons.setdefault(n.person_id, []).append(n.nick)

    blocks: list[str] = [
        parse.build_persons_directory(chat_persons, chat_nicks_by_person=nicks_for_persons)
    ]

    if is_dm:
        author = next((u for u in repo.db.users if u.id == caller_tid), None)
        chat_ids = set(getattr(author, "chat_ids", []) or []) if author else set()
        chats = [c for c in repo.db.chats if c.id in chat_ids]
        if chats:
            persons_by_id = {p.id: p for p in chat_persons}
            members_by_chat: dict[int, list] = {}
            for c in chats:
                members = [p for p in chat_persons if str(c.id) in set(p.chat_last_seen.keys())]
                members_by_chat[c.id] = members[:30]
            nicks_by_chat: dict[int, list[tuple[str, str]]] = {}
            for n in repo.db.chat_nicknames:
                if n.chat_id in chat_ids:
                    p = persons_by_id.get(n.person_id) or repo.get_bill_person(n.person_id)
                    if p:
                        nicks_by_chat.setdefault(n.chat_id, []).append((n.nick, p.display_name))
            chats_block = parse.build_chats_directory(chats, members_by_chat, nicks_by_chat)
            if chats_block:
                blocks.append(chats_block)
    return "\n\n".join(blocks)


def _caller_name(repo, caller_tid: int) -> str | None:
    caller = repo.get_bill_person_by_telegram_id(caller_tid)
    if caller is None:
        user_obj = next((u for u in repo.db.users if u.id == caller_tid), None)
        if user_obj:
            caller, _ = repo.get_or_create_bill_person(
                telegram_id=caller_tid,
                display_name=getattr(user_obj, "stand_name", None) or user_obj.username or str(caller_tid),
                username=user_obj.username,
            )
    return caller.display_name if caller else None


def _build_prompt_input(
    repo, caller_tid: int, origin_chat_id: int | None, context_items: list[str],
    *, current_block: str | None = None, correction_text: str | None = None,
) -> str:
    caller_name = _caller_name(repo, caller_tid)
    chat_persons = chat_persons_for(repo, caller_tid, origin_chat_id)
    directory = build_directory_block(repo, caller_tid, origin_chat_id, chat_persons)

    if correction_text is not None:
        return (
            f"{directory}\n\n---\n\n"
            f"[ТЕКУЩИЕ ПОЗИЦИИ]\n{current_block or ''}\n\n---\n\n"
            f"[ИСПРАВЛЕНИЕ]\n{correction_text}\n"
        )

    context_text = "\n\n".join(context_items)
    if caller_name:
        context_text = f"Я = {caller_name}\n\n" + context_text
    return f"{directory}\n\n---\n\n{context_text}"


def _resolve_names(
    repo, caller_tid: int, origin_chat_id: int | None,
    raw_names: list[str], chat_persons: list, resolved: dict[str, str],
) -> tuple[dict[str, str], list[tuple[str, list]]]:
    """Match a set of raw names to persons. Returns (resolved_map, resolve_queue).

    Confident matches (bound persons) go to resolved_map; ambiguous/unknown go to
    resolve_queue with candidate lists, exactly like session._ingest_ai_rows.
    """
    users_map = {u.id: u for u in repo.db.users}
    all_persons = repo.db.bill_persons
    mkwargs = match_kwargs_for(repo, caller_tid)

    seen: dict[str, str] = {}
    for raw in raw_names:
        raw = (raw or "").strip()
        if not raw or raw == "-":
            continue
        key = parse.norm_name_key(raw)
        if key not in seen:
            seen[key] = raw

    out_resolved = dict(resolved)
    resolve_queue: list[tuple[str, list]] = []
    for key, raw in seen.items():
        if key in out_resolved:
            continue
        person, candidates = match_name(
            raw, all_persons, users_map,
            caller_telegram_id=caller_tid, origin_chat_id=origin_chat_id, **mkwargs,
        )
        if person and person.telegram_id:
            out_resolved[key] = person.id
        elif candidates:
            resolve_queue.append((raw, candidates))
        else:
            resolve_queue.append((raw, chat_persons))
    return out_resolved, resolve_queue


async def run_collect(
    repo, *,
    caller_tid: int,
    origin_chat_id: int | None,
    context_items: list[str],
    resolved_map: dict[str, str] | None = None,
    current_block: str | None = None,
    correction_text: str | None = None,
) -> CollectResult | None:
    """Run the collect AI over context, parse positions + participants, resolve names.

    Returns None on AI failure (caller decides how to surface it). Builds no
    transactions and creates no persons — the caller resolves `resolve_queue` and
    then materialises rows via `parse.collect_rows_to_undistributed_transactions`.
    """
    if not context_items and correction_text is None:
        return CollectResult()

    prompt_input = _build_prompt_input(
        repo, caller_tid, origin_chat_id, context_items,
        current_block=current_block, correction_text=correction_text,
    )
    try:
        ai_response = await make_openrouter_query(
            user_id=f"bills_collect_{caller_tid}",
            model=OpenRouterModel.GEMINI_25_FLASH,
            messages=[("user", prompt_input)],
            system_prompt=_bill_collect_prompt(),
            max_tokens=4096,
            timeout_seconds=60.0,
        )
    except TimeoutError:
        logger.warning("bills collect AI timed out for user %s", caller_tid)
        return None
    except Exception as e:
        logger.exception("bills collect AI failed: %s", e)
        return None

    currency, item_rows, participant_names, new_persons, questions = parse.parse_collect_response(ai_response)

    chat_persons = chat_persons_for(repo, caller_tid, origin_chat_id)
    raw_names = [r.get("creditor_raw", "") for r in item_rows] + list(participant_names)
    out_resolved, resolve_queue = _resolve_names(
        repo, caller_tid, origin_chat_id, raw_names, chat_persons, resolved_map or {},
    )

    return CollectResult(
        currency=currency,
        item_rows=item_rows,
        participant_names=participant_names,
        new_person_names=new_persons,
        questions=questions,
        resolved_map=out_resolved,
        resolve_queue=resolve_queue,
    )
