"""Message formatting and keyboards for /bills."""
from __future__ import annotations

from typing import TYPE_CHECKING

from steward.data.models.bill_v2 import BillPerson, BillV2, UNKNOWN_PERSON_ID
from steward.framework import Button, Keyboard
from steward.helpers.bills_money import (
    apply_payments,
    compute_bill_debts,
    minor_to_display,
    net_debts,
    split_minor,
)

if TYPE_CHECKING:
    from steward.features.bills import BillsFeature


def compact_grid(buttons: list[Button], max_cols: int = 3, max_rows: int = 4) -> list[list[Button]]:
    """Pack `buttons` into ≤ max_rows rows of ≤ max_cols cells, minimizing rows.

    Always fills max_cols per row before wrapping (the last row may be partial).
    Excess buttons (beyond max_rows*max_cols) are dropped — callers that want
    pagination should use `paginate_grid` instead.
    """
    n = len(buttons)
    if n == 0:
        return []
    capacity = max_rows * max_cols
    if n > capacity:
        buttons = buttons[:capacity]
        n = capacity
    return [buttons[i:i + max_cols] for i in range(0, n, max_cols)]


def paginate_grid(
    buttons: list[Button],
    *,
    page: int,
    max_cols: int,
    max_rows: int,
    nav_factory=None,
) -> tuple[list[list[Button]], int, int]:
    """Slice `buttons` to one page (max_cols × max_rows) and append a nav row when needed.

    Returns (rows_with_nav, page, total_pages). `nav_factory(page)` must return a
    Button for that target page (called for prev/next + the centre indicator).
    """
    per_page = max(1, max_cols * max_rows)
    n = len(buttons)
    total_pages = max(1, -(-n // per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    chunk = buttons[start:start + per_page]
    rows = [chunk[i:i + max_cols] for i in range(0, len(chunk), max_cols)]
    if total_pages > 1 and nav_factory is not None:
        nav: list[Button] = []
        if page > 0:
            nav.append(nav_factory(page - 1, "« Пред"))
        nav.append(nav_factory(page, f"{page + 1}/{total_pages}", noop=True))
        if page < total_pages - 1:
            nav.append(nav_factory(page + 1, "След »"))
        rows.append(nav)
    return rows, page, total_pages


def _mono_table(headers: list[str], rows: list[list[str]]) -> str:
    """Aligned monospace table inside a code block."""
    all_rows = [headers] + rows
    cols = len(headers)
    widths = [max(len(r[i]) if i < len(r) else 0 for r in all_rows) for i in range(cols)]
    lines = []
    for i, row in enumerate(all_rows):
        line = "  ".join((row[j] if j < len(row) else "").ljust(widths[j]) for j in range(cols))
        lines.append(line.rstrip())
        if i == 0:
            lines.append("  ".join("─" * w for w in widths))
    return "```\n" + "\n".join(lines) + "\n```"


def pname(person_id: str, by_id: dict[str, BillPerson]) -> str:
    if not person_id or person_id == UNKNOWN_PERSON_ID:
        return "?"
    p = by_id.get(person_id)
    if not p:
        return "?"
    if p.telegram_username:
        return f"@{p.telegram_username}"
    return p.display_name


def _short_name(person_id: str, by_id: dict[str, BillPerson], max_len: int = 14) -> str:
    """Short name for table cells — truncate if needed."""
    name = pname(person_id, by_id)
    return name[:max_len] if len(name) > max_len else name


def _debt_table(debts: dict[str, dict[str, int]], by_id: dict[str, BillPerson], currency: str = "BYN") -> str:
    rows = []
    for debtor, creds in sorted(debts.items()):
        for creditor, amount in sorted(creds.items(), key=lambda x: -x[1]):
            if amount <= 0:
                continue
            rows.append([pname(debtor, by_id), "→", pname(creditor, by_id), minor_to_display(amount, currency)])
    if not rows:
        return ""
    return _mono_table(["Кто", "", "Кому", "Сумма"], rows)


def _tx_table(txs: list, by_id: dict[str, BillPerson], currency: str = "BYN") -> str:
    rows = []
    for tx in txs:
        total = minor_to_display(tx.unit_price_minor * tx.quantity, currency)
        cred = _short_name(tx.creditor, by_id)
        debtors = []
        for asg in tx.assignments:
            names = [_short_name(d, by_id) for d in asg.debtors if d != tx.creditor]
            if names:
                debtors.extend(names)
            elif not asg.debtors:
                debtors.append("?")
        debts_str = ", ".join(dict.fromkeys(debtors)) or "—"
        name = tx.item_name[:20]
        flag = " ⚠" if tx.incomplete else ""
        rows.append([f"{name}{flag}", total, cred, debts_str])
    return _mono_table(["Позиция", "Сумма", "Платил", "Должник"], rows)


def _compute_balances(bills: list[BillV2], person_id: str | None, payments: list):
    """Compute (owe, owed, pair_totals) across all open bills in `bills`."""
    from collections import defaultdict

    owe: dict[str, int] = defaultdict(int)
    owed: dict[str, int] = defaultdict(int)
    pair_totals: dict[tuple[str, str], int] = defaultdict(int)

    for bill in bills:
        if bill.closed:
            continue
        raw = compute_bill_debts(bill.transactions, bill.currency)
        net = net_debts(raw)
        bp = [p for p in payments if bill.id in p.bill_ids]
        after = apply_payments(net, bp, clamp_zero=True)
        for debtor, creds in after.items():
            for creditor, amt in creds.items():
                if amt > 0:
                    pair_totals[(debtor, creditor)] += amt
        if person_id:
            for cred, amt in after.get(person_id, {}).items():
                if amt > 0:
                    owe[cred] += amt
            for deb, per_cred in after.items():
                if deb != person_id and per_cred.get(person_id, 0) > 0:
                    owed[deb] += per_cred[person_id]

    return owe, owed, pair_totals


def format_overview(
    bills: list[BillV2],
    person_id: str | None,
    by_id: dict[str, BillPerson],
    payments: list,
    *,
    all_mode: bool = False,
) -> str:
    owe, owed, _ = _compute_balances(bills, person_id, payments)

    open_count = sum(1 for b in bills if not b.closed)
    closed_count = sum(1 for b in bills if b.closed)
    title = "Все счета" if all_mode else "Мои счета"
    counts = f"{open_count} открытых"
    if all_mode and closed_count:
        counts += f", {closed_count} закрытых"
    lines = [f"🧾 *{title}* ({counts})\n"]

    if owed:
        rows = [
            [pname(pid, by_id), minor_to_display(amt)]
            for pid, amt in sorted(owed.items(), key=lambda x: -x[1])
        ]
        lines.append("🔪 *Тебе должны:*")
        lines.append(_mono_table(["Кто", "Сумма"], rows))
        lines.append("")
    if owe:
        rows = [
            [pname(pid, by_id), minor_to_display(amt)]
            for pid, amt in sorted(owe.items(), key=lambda x: -x[1])
        ]
        lines.append("🥺 *Ты должен:*")
        lines.append(_mono_table(["Кому", "Сумма"], rows))
        lines.append("")
    if not owe and not owed and not all_mode:
        lines.append("_Нет открытых долгов_ ✨\n")

    return "\n".join(lines)


def format_pairs(
    bills: list[BillV2],
    by_id: dict[str, BillPerson],
    payments: list,
    *,
    all_mode: bool = False,
) -> str:
    """Render the cross-cut debt table across all open bills in `bills`."""
    _, _, pair_totals = _compute_balances(bills, None, payments)
    scope = "по всем счетам" if all_mode else "в твоих счетах"
    title = f"⚖️ *Общие долги {scope}*"
    if not pair_totals:
        return f"{title}\n\n_Нет открытых долгов_ ✨"
    rows = [
        [pname(d, by_id), "→", pname(c, by_id), minor_to_display(a)]
        for (d, c), a in sorted(pair_totals.items(), key=lambda x: -x[1])
    ]
    return f"{title}\n{_mono_table(['Кто', '', 'Кому', 'Сумма'], rows)}"


def format_audit(bills: list[BillV2], payments: list) -> str:
    return "📋 *Аудит:*\n" + "\n".join(_audit_lines(bills, payments))


def _audit_lines(bills: list[BillV2], payments: list) -> list[str]:
    out: list[str] = []
    for bill in sorted(bills, key=lambda b: (b.closed, -b.id)):
        gross = sum(tx.unit_price_minor * tx.quantity for tx in bill.transactions)
        raw = compute_bill_debts(bill.transactions, bill.currency)
        net = net_debts(raw)
        bp = [p for p in payments if bill.id in p.bill_ids]
        after = apply_payments(net, bp, clamp_zero=True)
        outstanding = sum(
            amt for creds in after.values() for amt in creds.values() if amt > 0
        )
        flag = "🔒" if bill.closed else ("✅" if outstanding == 0 else "🔓")
        name = bill.name[:32]
        debt_part = (
            f" · долг {minor_to_display(outstanding, bill.currency)}"
            if outstanding else " · ✓ закрыт по долгам"
        )
        out.append(
            f"{flag} `#{bill.id}` *{name}* — {len(bill.transactions)} поз., "
            f"{len(bill.participants)} уч., итог {minor_to_display(gross, bill.currency)}, "
            f"оплат {len(bp)}{debt_part}"
        )
    if not out:
        return ["_(нет счетов)_"]
    return out


def format_bill_detail(
    bill: BillV2,
    person_id: str | None,
    by_id: dict[str, BillPerson],
    payments: list,
) -> str:
    status = "🔒 Закрыт" if bill.closed else "🔓 Открыт"
    incomplete = sum(1 for tx in bill.transactions if tx.incomplete)
    inc_str = f" (⚠️ {incomplete} не назначены)" if incomplete else ""

    lines = [
        f"🧾 *{bill.name}* \\#{bill.id}  {status}",
        f"Автор: {pname(bill.author_person_id, by_id)} · {bill.currency}",
        f"📋 Позиций: {len(bill.transactions)}{inc_str}",
        "",
        _tx_table(bill.transactions[:20], by_id, bill.currency),
    ]
    if len(bill.transactions) > 20:
        lines.append(f"  … и ещё {len(bill.transactions) - 20}")

    raw = compute_bill_debts(bill.transactions, bill.currency)
    net = net_debts(raw)
    bp = [p for p in payments if bill.id in p.bill_ids]
    after = apply_payments(net, bp, clamp_zero=True)
    any_debt = any(amt > 0 for creds in after.values() for amt in creds.values())

    if any_debt:
        lines.append("\n⚖️ Кто кому:")
        lines.append(_debt_table(after, by_id, bill.currency))

    if person_id:
        my_debts = {c: a for c, a in after.get(person_id, {}).items() if a > 0}
        owed_to_me = {d: v.get(person_id, 0) for d, v in after.items() if v.get(person_id, 0) > 0}
        if my_debts or owed_to_me:
            lines.append("\n👤 Лично ты:")
            for cid, amt in my_debts.items():
                lines.append(f"  → {pname(cid, by_id)}: {minor_to_display(amt, bill.currency)}")
            for did, amt in owed_to_me.items():
                lines.append(f"  ← {pname(did, by_id)}: {minor_to_display(amt, bill.currency)}")

    return "\n".join(lines)


def format_bill_created(bill: BillV2, by_id: dict[str, BillPerson]) -> str:
    lines = [
        f"✅ Счёт «{bill.name}» \\#{bill.id} создан!",
        f"Позиций: {len(bill.transactions)} · Участников: {len(bill.participants)}",
    ]
    incomplete = sum(1 for tx in bill.transactions if tx.incomplete)
    if incomplete:
        lines.append(f"⚠️ {incomplete} позиций не назначены")

    raw = compute_bill_debts(bill.transactions, bill.currency)
    net = net_debts(raw)
    any_debt = any(amt > 0 for creds in net.values() for amt in creds.values())
    if any_debt:
        lines.append("\n⚖️ Кто кому:")
        lines.append(_debt_table(net, by_id, bill.currency))

    return "\n".join(lines)


def format_preview(
    transactions: list,
    by_id: dict[str, BillPerson],
    currency: str = "BYN",
    resolved_map: dict[str, str] | None = None,
) -> str:
    lines: list[str] = []

    if resolved_map:
        name_lines = []
        for raw_key, pid in sorted(resolved_map.items()):
            p = by_id.get(pid)
            if p and raw_key != p.display_name.strip().casefold():
                name_lines.append(f"  {raw_key.title()} → {pname(pid, by_id)} ✓")
        if name_lines:
            lines.append("👥 Участники:")
            lines.extend(name_lines)
            lines.append("")

    lines.append(f"📋 Найдено позиций: {len(transactions)}")
    lines.append("")

    from collections import defaultdict
    debt_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    table_rows = []
    for tx in transactions:
        total = minor_to_display(tx.unit_price_minor * tx.quantity, currency)
        cred = _short_name(tx.creditor, by_id)

        person_shares: dict[str, int] = {}
        for asg in tx.assignments:
            if not asg.debtors:
                continue
            asg_total = tx.unit_price_minor * asg.unit_count
            ordered = sorted(asg.debtors, key=lambda d: d == tx.creditor)
            shares = split_minor(asg_total, len(ordered))
            for debtor, share in zip(ordered, shares):
                person_shares[debtor] = person_shares.get(debtor, 0) + share
                if debtor != tx.creditor and debtor != UNKNOWN_PERSON_ID and tx.creditor != UNKNOWN_PERSON_ID:
                    debt_totals[debtor][tx.creditor] += share

        debtor_parts = []
        n = len(person_shares)
        for pid, amount in person_shares.items():
            name = _short_name(pid, by_id)
            amt = minor_to_display(amount, currency)
            debtor_parts.append(f"{name}:{amt}" if n > 1 else name)

        name = tx.item_name[:18]
        flag = " ⚠" if tx.incomplete else ""
        debtors_str = ", ".join(debtor_parts) if debtor_parts else "?"
        table_rows.append([f"{name}{flag}", total, cred, debtors_str])

    lines.append(_mono_table(["Позиция", "Сумма", "Платил", "Кто должен"], table_rows))

    if debt_totals:
        net = net_debts(dict(debt_totals))
        any_debt = any(amt > 0 for creds in net.values() for amt in creds.values())
        if any_debt:
            lines.append("\n⚖️ Итого:")
            lines.append(_debt_table(net, by_id, currency))

    lines.append("")
    lines.append(
        "_Нашёл что-то неправильное? Скажи голосом или текстом —_\n"
        "_например «Саша съел половину пиццы, остальные делят остальное»._"
    )

    return "\n".join(lines)


def kb_collect(feature: "BillsFeature", context_items: list[str] | None = None) -> Keyboard:
    rows: list[list[Button]] = []
    if context_items:
        photos = sum(1 for c in context_items if c.startswith("[Фото]"))
        voices = sum(1 for c in context_items if c.startswith("[Голосовое]"))
        texts = sum(1 for c in context_items if c.startswith("[Текст]"))
        parts = []
        if photos: parts.append(f"📷 {photos}")
        if voices: parts.append(f"🎤 {voices}")
        if texts: parts.append(f"📝 {texts}")
        if parts:
            rows.append([feature.cb("bills:noop").button(" · ".join(parts))])
    rows.append([
        feature.cb("bills:add_done").button("✅ Готово"),
        feature.cb("bills:add_cancel").button("❌ Отмена"),
    ])
    return Keyboard.grid(rows)


def kb_confirm(feature: "BillsFeature") -> Keyboard:
    return Keyboard.grid([
        [
            feature.cb("bills:add_confirm").button("✅ Сохранить"),
            feature.cb("bills:add_cancel").button("❌ Отмена"),
        ],
        [
            feature.cb("bills:add_more").button("📎 Ещё контекст"),
            feature.cb("bills:change_list").button("🔄 Людей"),
        ],
    ])


def kb_disambiguation(feature: "BillsFeature", candidates: list) -> Keyboard:
    """Candidates for the current name being resolved (always resolve_queue[0])."""
    buttons = [
        feature.cb("bills:name_pick").button(p.display_name, person_id=p.id)
        for p in candidates[:6]
    ]
    rows = compact_grid(buttons, max_cols=2)
    rows.append([feature.cb("bills:name_new").button("➕ Новый человек")])
    return Keyboard.grid(rows)


def kb_change_list(feature: "BillsFeature", resolved_map: dict[str, str], by_id: dict[str, BillPerson]) -> Keyboard:
    sorted_keys = sorted(resolved_map.keys())
    buttons = []
    for idx, key in enumerate(sorted_keys):
        p = by_id.get(resolved_map[key])
        label = f"{key.title()} → {p.display_name if p else '?'}"
        buttons.append(feature.cb("bills:chg").button(label[:30], idx=idx))
    rows = compact_grid(buttons, max_cols=2)
    rows.append([feature.cb("bills:change_back").button("« Назад")])
    return Keyboard.grid(rows)


def kb_change_pick(feature: "BillsFeature", idx: int, persons: list) -> Keyboard:
    buttons = [
        feature.cb("bills:chgp").button(p.display_name, idx=idx, person_id=p.id)
        for p in persons[:10]
    ]
    rows = compact_grid(buttons, max_cols=2)
    rows.append([feature.cb("bills:chgn").button("➕ Новый", idx=idx)])
    rows.append([feature.cb("bills:change_list").button("« Назад")])
    return Keyboard.grid(rows)


def kb_bill(feature: "BillsFeature", bill: BillV2, person_id: str | None, is_admin: bool, payments: list) -> Keyboard:
    rows: list[list[Button]] = []
    can_edit = is_admin or (person_id and person_id == bill.author_person_id)
    is_participant = person_id and person_id in bill.participants and person_id != bill.author_person_id

    if not bill.closed:
        rows.append([
            feature.cb("bills:pay_start").button("💸 Оплатить", bill_id=bill.id),
            feature.cb("bills:got_start").button("✅ Получил", bill_id=bill.id),
        ])
        if is_participant:
            rows.append([feature.cb("bills:suggest_start").button("➕ Предложить", bill_id=bill.id)])
        if can_edit:
            rows.append([feature.cb("bills:close").button("🔒 Закрыть", bill_id=bill.id)])
    elif can_edit:
        rows.append([feature.cb("bills:reopen").button("🔓 Открыть", bill_id=bill.id)])

    rows.append([feature.cb("bills:overview").button("« Назад")])
    return Keyboard.grid(rows)


def kb_pay_global(
    feature: "BillsFeature",
    person_id: str,
    by_id: dict[str, BillPerson],
    all_bills: list[BillV2],
    payments: list,
    source_bill_id: int,
    *,
    back_to_overview: bool = False,
) -> tuple[str, Keyboard]:
    """NET debts across ALL open bills between this person and others."""
    from collections import defaultdict
    total_owe: dict[str, int] = defaultdict(int)

    for bill in all_bills:
        if bill.closed:
            continue
        raw = compute_bill_debts(bill.transactions, bill.currency)
        net = net_debts(raw)
        bp = [p for p in payments if bill.id in p.bill_ids]
        after = apply_payments(net, bp, clamp_zero=True)
        for cred, amt in after.get(person_id, {}).items():
            if amt > 0:
                total_owe[cred] += amt
        for deb, creds in after.items():
            if deb != person_id and creds.get(person_id, 0) > 0:
                total_owe[person_id] = total_owe.get(person_id, 0)

    my_debts = {c: a for c, a in total_owe.items() if a > 0 and c != person_id}

    def _back_btn():
        if back_to_overview:
            return feature.cb("bills:overview").button("« Назад")
        return feature.cb("bills:view").button("« Назад", bill_id=source_bill_id)

    if not my_debts:
        return "💸 Нет долгов ✨", Keyboard.row(_back_btn())

    lines = ["💸 Твои долги (по всем счетам):\n"]
    rows: list[list[Button]] = []
    for cred_id, amount in sorted(my_debts.items(), key=lambda x: -x[1]):
        name = pname(cred_id, by_id)
        amt = minor_to_display(amount)
        lines.append(f"  → {name}: {amt}")
        rows.append([feature.cb("bills:qpay").button(
            f"💸 {name} {amt}",
            bill_id=source_bill_id,
            creditor_short=cred_id[:20],
            amount=amount,
        )])
    rows.append([feature.cb("bills:pay_manual").button("✍️ Другая сумма", bill_id=source_bill_id)])
    rows.append([_back_btn()])
    return "\n".join(lines), Keyboard.grid(rows)


def kb_got_global(
    feature: "BillsFeature",
    person_id: str,
    by_id: dict[str, BillPerson],
    all_bills: list[BillV2],
    payments: list,
    source_bill_id: int,
    *,
    back_to_overview: bool = False,
) -> tuple[str, Keyboard]:
    """NET debts owed TO this person across all open bills, with quick-confirm buttons."""
    from collections import defaultdict
    owed_to_me: dict[str, int] = defaultdict(int)

    for bill in all_bills:
        if bill.closed:
            continue
        raw = compute_bill_debts(bill.transactions, bill.currency)
        net = net_debts(raw)
        bp = [p for p in payments if bill.id in p.bill_ids]
        after = apply_payments(net, bp, clamp_zero=True)
        for debtor, creds in after.items():
            amt = creds.get(person_id, 0)
            if amt > 0:
                owed_to_me[debtor] += amt

    def _back_btn():
        if back_to_overview:
            return feature.cb("bills:overview").button("« Назад")
        return feature.cb("bills:view").button("« Назад", bill_id=source_bill_id)

    if not owed_to_me:
        return "✅ Тебе никто ничего не должен ✨", Keyboard.row(_back_btn())

    lines = ["✅ *Тебе должны* (по всем счетам):\n"]
    rows: list[list[Button]] = []
    for debtor_id, amount in sorted(owed_to_me.items(), key=lambda x: -x[1]):
        name = pname(debtor_id, by_id)
        amt = minor_to_display(amount)
        lines.append(f"  ← {name}: {amt}")
        rows.append([feature.cb("bills:qgot").button(
            f"✅ {name} {amt}",
            bill_id=source_bill_id,
            debtor_short=debtor_id[:20],
            amount=amount,
        )])
    rows.append([feature.cb("bills:got_manual").button("✍️ Другая сумма", bill_id=source_bill_id)])
    rows.append([_back_btn()])
    return "\n".join(lines), Keyboard.grid(rows)


def kb_bill_buttons(feature: "BillsFeature", bills: list[BillV2]) -> list[Button]:
    """Build view-bill buttons for a list of bills (used in list views)."""
    return [
        feature.cb("bills:view").button(f"#{b.id} {b.name[:18]}", bill_id=b.id)
        for b in bills
    ]


def kb_resolve_list(
    feature: "BillsFeature",
    unbound: list[BillPerson],
    *,
    show_back: bool = True,
) -> Keyboard:
    """List of unbound persons with «Связать» buttons leading to a per-person picker."""
    rows: list[list[Button]] = []
    for p in unbound[:20]:
        rows.append([
            feature.cb("bills:resolve").button(
                f"🔗 {p.display_name[:30]}",
                person_short=p.id[:20],
            )
        ])
    if show_back:
        rows.append([feature.cb("bills:overview").button("« Назад")])
    return Keyboard.grid(rows)


def select_history(
    payments: list,
    my_person_id: str | None,
    bills_by_id: dict,
    *,
    filter_: str = "all",
    show_chat_only_for: int | None = None,
) -> list:
    """Filter + sort payments for history view (newest first)."""
    items = list(payments)
    if show_chat_only_for is not None:
        bill_ids_for_chat = {
            b.id for b in bills_by_id.values()
            if getattr(b, "origin_chat_id", None) == show_chat_only_for
        }
        items = [
            p for p in items
            if p.initiated_chat_id == show_chat_only_for
            or any(bid in bill_ids_for_chat for bid in (p.bill_ids or []))
        ]
    if my_person_id:
        if filter_ == "recv":
            items = [p for p in items if p.creditor == my_person_id]
        elif filter_ == "sent":
            items = [p for p in items if p.debtor == my_person_id]
        else:
            items = [
                p for p in items
                if p.creditor == my_person_id or p.debtor == my_person_id
            ]
    items.sort(key=lambda p: p.created_at, reverse=True)
    return items


def _history_status_icon(status: str, is_refund: bool = False) -> str:
    """Single-cell, single-codepoint glyphs so _mono_table stays aligned.

    `↩` marks a refund — a payment that went *against* the usual direction
    of debt and thus increases what the receiver owes the sender (see
    BillPaymentV2.is_refund). Appears mostly after legacy migration.
    """
    if is_refund:
        return "↩"
    return {
        "confirmed": "✓",
        "auto_confirmed": "✓",
        "pending": "…",
        "rejected": "✗",
    }.get(status, "·")


def render_history_table(
    chunk: list,
    by_id: dict[str, BillPerson],
    bills_by_id: dict,
    *,
    my_person_id: str | None = None,
    head: str = "",
) -> str:
    """Render a chunk of payments as the mono-aligned history table."""
    if not chunk:
        return f"{head}\n\n_Пусто._" if head else "_Пусто._"

    rows: list[list[str]] = []
    for p in chunk:
        d = p.created_at.strftime("%m-%d") if hasattr(p.created_at, "strftime") else "?"
        who = (
            f"{_short_name(p.debtor, by_id, max_len=10)} → "
            f"{_short_name(p.creditor, by_id, max_len=10)}"
        )
        if my_person_id and p.creditor == my_person_id:
            who = f"← {_short_name(p.debtor, by_id, max_len=12)}"
        elif my_person_id and p.debtor == my_person_id:
            who = f"→ {_short_name(p.creditor, by_id, max_len=12)}"
        amt = minor_to_display(p.amount_minor, p.currency)
        ico = _history_status_icon(p.status, getattr(p, "is_refund", False))
        bill_part = ""
        if p.bill_ids:
            bid = p.bill_ids[0]
            b = bills_by_id.get(bid)
            bname = (b.name[:14] if b else f"#{bid}") if b else f"#{bid}"
            bill_part = f"#{bid} {bname}"
        rows.append([d, ico, who, amt, bill_part])
    table = _mono_table(["Дата", "", "Кто", "Сумма", "Счёт"], rows)
    return f"{head}\n{table}" if head else table


def kb_resolve_picker(
    feature: "BillsFeature",
    person: BillPerson,
    candidates: list[tuple[int, str, float]],
) -> Keyboard:
    """Picker for one unbound person — list of TG candidates from chat + extras.

    `candidates` items: (telegram_id, display, score).
    """
    rows: list[list[Button]] = []
    for tid, label, _score in candidates[:8]:
        rows.append([
            feature.cb("bills:resolve_pick").button(
                label[:36],
                person_short=person.id[:20],
                user_tid=tid,
            )
        ])
    rows.append([
        feature.cb("bills:resolve_byname").button(
            "✏️ По @username",
            person_short=person.id[:20],
        ),
    ])
    rows.append([
        feature.cb("bills:resolve_skip").button(
            "🚫 Не нужно (скрыть)",
            person_short=person.id[:20],
        ),
    ])
    rows.append([feature.cb("bills:resolve_back").button("« Назад")])
    return Keyboard.grid(rows)
