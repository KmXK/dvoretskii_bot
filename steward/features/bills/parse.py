"""AI response parsing for /bills — extracts transactions from structured text."""
from __future__ import annotations

import re
import uuid

from steward.data.models.bill_v2 import (
    BillItemAssignment,
    BillTransaction,
    UNKNOWN_PERSON_ID,
)


def norm_name_key(name: str) -> str:
    """Normalize a name for map lookup: collapse case and whitespace, keep ё/е distinct."""
    return (name or "").strip().casefold()


def _parse_price(s: str) -> int | None:
    s = s.strip().replace(",", ".")
    if not s:
        return None
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return None


def parse_ai_response(text: str) -> tuple[str, list[dict], list[str], list[dict]]:
    """Parse structured AI output into (currency, rows, new_person_names, questions).

    Each row: {name, price_minor, quantity, debtors_raw, creditor_raw, source, group_id}
    Each question: {text, options}
    """
    currency = "BYN"
    rows: list[dict] = []
    new_persons: list[str] = []
    questions: list[dict] = []

    def _section(header: str) -> str:
        m = re.search(rf"\[{header}\](.*?)(?=\[|$)", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    for line in _section("META").splitlines():
        if line.strip().lower().startswith("currency:"):
            currency = line.split(":", 1)[1].strip().upper() or "BYN"

    for line in _section("ОБЩЕЕ").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6 or not parts[0]:
            continue
        price_minor = _parse_price(parts[1])
        if price_minor is None or price_minor == 0:
            continue
        try:
            quantity = max(1, round(float(parts[2])))
        except (ValueError, TypeError):
            continue
        rows.append({
            "name": parts[0],
            "price_minor": price_minor,
            "quantity": quantity,
            "debtors_raw": parts[3],
            "creditor_raw": parts[4],
            "source": (parts[5] if len(parts) > 5 else "text").lower(),
            "group_id": (parts[6].strip() if len(parts) > 6 else ""),
        })

    for line in _section("ДАННЫЕ").splitlines():
        name = line.strip().split("|")[0].strip()
        if name:
            new_persons.append(name)

    for line in _section("ВОПРОСЫ").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        q_text = parts[0]
        if not q_text:
            continue
        options = [p for p in parts[1:] if p]
        if not options or options[-1].lower() != "другое":
            options.append("Другое")
        questions.append({"text": q_text, "options": options})

    return currency, rows, new_persons, questions


def rows_to_transactions(rows: list[dict], name_to_id: dict[str, str]) -> list[BillTransaction]:
    """Convert parsed AI rows into BillTransaction objects.

    Rows sharing a non-empty group_id are merged into one multi-assignment transaction.
    """

    def _resolve(raw: str) -> str:
        raw = raw.strip()
        if not raw or raw == "-":
            return UNKNOWN_PERSON_ID
        return name_to_id.get(norm_name_key(raw), UNKNOWN_PERSON_ID)

    def _resolve_debtors(raw: str) -> list[str]:
        if not raw.strip() or raw.strip() == "-":
            return []
        return [pid for name in raw.split(",")
                if (pid := name_to_id.get(norm_name_key(name))) and pid != UNKNOWN_PERSON_ID]

    def _make_tx(first: dict, assignments: list[BillItemAssignment]) -> BillTransaction:
        return BillTransaction(
            id=str(uuid.uuid4()),
            item_name=first["name"],
            creditor=_resolve(first["creditor_raw"]),
            unit_price_minor=first["price_minor"],
            quantity=sum(a.unit_count for a in assignments),
            assignments=assignments,
            source=first.get("source", "text"),
            incomplete=any(not a.debtors for a in assignments),
        )

    groups: dict[str, list[dict]] = {}
    ungrouped: list[dict] = []
    for row in rows:
        gid = row.get("group_id", "").strip()
        if gid:
            groups.setdefault(gid, []).append(row)
        else:
            ungrouped.append(row)

    txs: list[BillTransaction] = []

    for group_rows in groups.values():
        assignments = [BillItemAssignment(unit_count=r["quantity"], debtors=_resolve_debtors(r["debtors_raw"]))
                       for r in group_rows]
        txs.append(_make_tx(group_rows[0], assignments))

    for row in ungrouped:
        debtors = _resolve_debtors(row["debtors_raw"])
        txs.append(BillTransaction(
            id=str(uuid.uuid4()),
            item_name=row["name"],
            creditor=_resolve(row["creditor_raw"]),
            unit_price_minor=row["price_minor"],
            quantity=row["quantity"],
            assignments=[BillItemAssignment(unit_count=row["quantity"], debtors=debtors)],
            source=row.get("source", "text"),
            incomplete=not debtors,
        ))

    return txs


def build_persons_directory(
    persons: list,
    *,
    chat_nicks_by_person: dict[str, list[str]] | None = None,
) -> str:
    """Build the [СПРАВОЧНИК ЛЮДЕЙ] block for the AI prompt.

    `chat_nicks_by_person` adds chat-scoped nicknames inline next to each person.
    """
    lines = ["[СПРАВОЧНИК ЛЮДЕЙ]"]
    chat_nicks_by_person = chat_nicks_by_person or {}
    for p in persons:
        extras = " / ".join(filter(None, [
            ", ".join(p.aliases) if p.aliases else "",
            f"@{p.telegram_username}" if p.telegram_username else "",
            (
                "клички: " + ", ".join(chat_nicks_by_person[p.id])
                if chat_nicks_by_person.get(p.id) else ""
            ),
        ]))
        lines.append(f"{p.display_name}" + (f" ({extras})" if extras else ""))
    return "\n".join(lines)


def build_chats_directory(
    chats: list,
    members_by_chat: dict[int, list],
    nicks_by_chat: dict[int, list[tuple[str, str]]] | None = None,
) -> str:
    """Build the [ИЗВЕСТНЫЕ ЧАТЫ] block for DM mode.

    `chats`: list of Chat objects to include.
    `members_by_chat`: {chat_id: [BillPerson, ...]}.
    `nicks_by_chat`: {chat_id: [(nick, person_display_name), ...]}.
    """
    if not chats:
        return ""
    nicks_by_chat = nicks_by_chat or {}
    lines = ["[ИЗВЕСТНЫЕ ЧАТЫ]"]
    for c in chats:
        aliases = ", ".join(c.aliases) if getattr(c, "aliases", None) else ""
        header = f"## {c.name}"
        if aliases:
            header += f" (алиасы: {aliases})"
        lines.append(header)
        members = members_by_chat.get(c.id, [])
        if members:
            lines.append(
                "  люди: " + ", ".join(p.display_name for p in members[:30])
            )
        chat_nicks = nicks_by_chat.get(c.id, [])
        if chat_nicks:
            lines.append(
                "  клички: " + ", ".join(f"{nick}={who}" for nick, who in chat_nicks)
            )
    return "\n".join(lines)


def parsed_rows_to_general_block(rows: list[dict]) -> str:
    """Re-emit a [ОБЩЕЕ] block from parsed_rows (the dicts produced by parse_ai_response)."""
    lines = [
        "[ОБЩЕЕ]",
        "Наименование | Цена_за_ед | Кол-во | Должник(и) | Кредитор | Источник | GroupId",
    ]
    for r in rows:
        price_minor = r.get("price_minor", 0)
        unit_price = f"{price_minor / 100:.2f}".rstrip("0").rstrip(".")
        if price_minor == 0:
            unit_price = "0"
        src = (r.get("source", "text") or "text").capitalize()
        lines.append(
            f"{r.get('name','')} | {unit_price} | {r.get('quantity',1)} | "
            f"{r.get('debtors_raw','')} | {r.get('creditor_raw','')} | "
            f"{src} | {r.get('group_id','')}"
        )
    return "\n".join(lines)


def transactions_to_general_block(transactions: list, by_id: dict) -> str:
    """Re-emit a [ОБЩЕЕ] block from BillTransaction objects.

    Used to feed the current bill state into the correction prompt so
    the model can edit it. Mirrors the parser's expected schema:
        Наименование | Цена_за_ед | Кол-во | Должник(и) | Кредитор | Источник | GroupId
    """

    def _name(pid: str) -> str:
        if pid == UNKNOWN_PERSON_ID:
            return "-"
        p = by_id.get(pid)
        return p.display_name if p else "-"

    lines = [
        "[ОБЩЕЕ]",
        "Наименование | Цена_за_ед | Кол-во | Должник(и) | Кредитор | Источник | GroupId",
    ]
    group_counter = 0
    for tx in transactions:
        cred = _name(tx.creditor)
        src = (getattr(tx, "source", "text") or "text").capitalize()
        # Convert kopecks back to display: dot decimal, trim trailing zeros.
        unit_price = f"{tx.unit_price_minor / 100:.2f}".rstrip("0").rstrip(".")
        if tx.unit_price_minor == 0:
            unit_price = "0"
        if len(tx.assignments) > 1:
            group_counter += 1
            gid = f"G{group_counter}"
        else:
            gid = ""
        for asg in tx.assignments:
            debtors_str = ", ".join(_name(d) for d in asg.debtors) if asg.debtors else "-"
            lines.append(
                f"{tx.item_name} | {unit_price} | {asg.unit_count} | {debtors_str} | {cred} | {src} | {gid}"
            )
    return "\n".join(lines)
