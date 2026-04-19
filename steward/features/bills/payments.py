from collections import defaultdict
from typing import Callable

from steward.data.models.bill import Bill, Payment, Transaction


def debts_from_transactions(
    transactions: list[Transaction],
) -> dict[str, dict[str, float]]:
    debts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        per_person = t.amount / len(t.debtors)
        for d in t.debtors:
            if d != t.creditor:
                debts[d][t.creditor] += per_person
    return debts


def apply_payments(
    debts: dict[str, dict[str, float]],
    payments: list[Payment],
    *,
    clamp_zero: bool = False,
) -> dict[str, dict[str, float]]:
    for p in payments:
        if not p.creditor:
            continue
        if p.person in debts and p.creditor in debts[p.person]:
            debts[p.person][p.creditor] -= p.amount
            if clamp_zero and debts[p.person][p.creditor] < 0:
                debts[p.person][p.creditor] = 0
    return debts


def payments_to_remove_for_closed(
    debts_closed: dict[str, dict[str, float]],
    payments: list[Payment],
) -> tuple[list[Payment], list[tuple[Payment, float]]]:
    to_remove: list[Payment] = []
    to_reduce: list[tuple[Payment, float]] = []
    remaining: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for debtor, creds in debts_closed.items():
        for creditor, amount in creds.items():
            remaining[debtor][creditor] = amount
    for p in sorted(payments, key=lambda x: x.timestamp):
        if not p.creditor:
            continue
        debt = remaining.get(p.person, {}).get(p.creditor, 0)
        if debt < 0.01:
            continue
        if p.amount <= debt + 0.01:
            to_remove.append(p)
            remaining[p.person][p.creditor] -= p.amount
        else:
            new_amount = round(p.amount - debt, 2)
            if new_amount < 0.01:
                to_remove.append(p)
            else:
                to_reduce.append((p, new_amount))
            remaining[p.person][p.creditor] = 0
    return to_remove, to_reduce


def net_direct_debts(
    debts: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    working: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for debtor, creds in debts.items():
        for creditor, amount in creds.items():
            if amount > 0.01:
                working[debtor][creditor] += amount
            elif amount < -0.01:
                working[creditor][debtor] += -amount
    people = set(working.keys()) | {c for creds in working.values() for c in creds}
    for a in people:
        for b in people:
            if a >= b:
                continue
            a_to_b = working[a].get(b, 0)
            b_to_a = working[b].get(a, 0)
            if a_to_b < 0.01 and b_to_a < 0.01:
                continue
            net = a_to_b - b_to_a
            working[a][b] = max(0, net)
            working[b][a] = max(0, -net)
    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for debtor, creds in working.items():
        for creditor, amount in creds.items():
            if amount > 0.01:
                result[debtor][creditor] = amount
    return {d: dict(cs) for d, cs in result.items() if cs}


def debts_to_list(debts: dict[str, dict[str, float]]) -> list[tuple[str, str, float]]:
    result = []
    for debtor, creds in debts.items():
        for creditor, amount in creds.items():
            if amount > 0.01:
                result.append((debtor, creditor, amount))
    return result


def bills_closable(
    bill_ids: list[int],
    all_bills: list[Bill],
    load_transactions: Callable[[str], list[Transaction]],
    payments: list[Payment],
) -> bool:
    bills_to_close = [b for b in all_bills if b.id in bill_ids]
    if len(bills_to_close) != len(bill_ids):
        return False
    other_bills = [b for b in all_bills if b.id not in bill_ids]
    tx_closed = []
    for b in bills_to_close:
        tx_closed.extend(load_transactions(b.file_id))
    tx_other = []
    for b in other_bills:
        tx_other.extend(load_transactions(b.file_id))
    debts_closed = debts_from_transactions(tx_closed)
    debts_closed = apply_payments(debts_closed, payments, clamp_zero=True)
    debts_closed = net_direct_debts(debts_closed)
    remaining = debts_to_list(debts_closed)
    return len(remaining) == 0


def parse_bill_ids(raw: str) -> list[int] | None:
    try:
        return [int(p) for p in raw.split()]
    except ValueError:
        return None


def apply_close(
    bills_to_close: list[Bill],
    payments: list[Payment],
    load_transactions,
) -> tuple[list[Payment], list[tuple[Payment, float]]]:
    tx_closed = []
    for b in bills_to_close:
        tx_closed.extend(load_transactions(b.file_id))
    debts_closed = debts_from_transactions(tx_closed)
    debts_closed = net_direct_debts(debts_closed)
    return payments_to_remove_for_closed(debts_closed, payments)


def participants_from_transactions(transactions: list[Transaction]) -> set[str]:
    out: set[str] = set()
    for t in transactions:
        out.update(t.debtors)
        out.add(t.creditor)
    return out


def payments_relevant_to_participants(
    payments: list[Payment], participants: set[str]
) -> list[Payment]:
    return [
        p
        for p in payments
        if p.person in participants or (p.creditor and p.creditor in participants)
    ]
