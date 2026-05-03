"""Integer-kopeck money arithmetic for /bills.

All amounts are stored as int minor units (1/100 of the base currency).
BYN: 1 ruble = 100 kopecks.  USD: 1 dollar = 100 cents.

Never use float for money — use these helpers.
"""

CURRENCY_SYMBOLS: dict[str, str] = {
    "BYN": "р",
    "RUB": "₽",
    "USD": "$",
    "EUR": "€",
    "UAH": "₴",
}

CURRENCY_PREFIX: set[str] = {"USD", "EUR"}


def minor_from_float(value: float) -> int:
    """Convert a float amount (e.g. 3.0) to minor units (300)."""
    from decimal import Decimal, ROUND_HALF_UP
    return int((Decimal(str(value)) * 100).to_integral_value(ROUND_HALF_UP))


def minor_to_float(minor: int) -> float:
    return minor / 100.0


def minor_to_display(minor: int, currency: str = "BYN") -> str:
    """Format minor units as a human-readable string.

    Examples:
        300  BYN -> "3 р"
        150  BYN -> "1.50 р"
        300  USD -> "$3"
        150  USD -> "$1.50"
    """
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    rubles, kopecks = divmod(abs(minor), 100)
    sign = "-" if minor < 0 else ""
    if kopecks == 0:
        amount_str = str(rubles)
    else:
        amount_str = f"{rubles}.{kopecks:02d}"
    if currency in CURRENCY_PREFIX:
        return f"{sign}{symbol}{amount_str}"
    return f"{sign}{amount_str} {symbol}"


def split_minor(total_minor: int, n: int) -> list[int]:
    """Split total_minor equally into n parts; distribute remainder to first slots.

    split_minor(1000, 3) -> [334, 333, 333]
    split_minor(100, 3)  -> [34, 33, 33]
    split_minor(0, 3)    -> [0, 0, 0]
    """
    if n <= 0:
        return []
    base, remainder = divmod(total_minor, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]


def compute_bill_debts(
    transactions,
    currency: str = "BYN",
) -> dict[str, dict[str, int]]:
    """Return {debtor_id: {creditor_id: amount_minor}} from a list of BillTransactions.

    Only processes transactions where assignments are defined.
    Transactions with all-empty-debtors assignments are skipped.
    """
    from collections import defaultdict
    from steward.data.models.bill_v2 import UNKNOWN_PERSON_ID

    debts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for tx in transactions:
        if tx.creditor == UNKNOWN_PERSON_ID:
            continue
        for asg in tx.assignments:
            if not asg.debtors:
                continue
            asg_total = tx.unit_price_minor * asg.unit_count
            # Non-payers first → get rounded up; payer last → absorbs rounding
            ordered = sorted(asg.debtors, key=lambda d: d == tx.creditor)
            shares = split_minor(asg_total, len(ordered))
            for debtor, share in zip(ordered, shares):
                if debtor == tx.creditor or debtor == UNKNOWN_PERSON_ID:
                    continue
                debts[debtor][tx.creditor] += share
    return debts


def net_debts(debts: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Collapse mutual debts A↔B, keep only the net positive direction."""
    from collections import defaultdict

    result: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    seen: set[tuple[str, str]] = set()
    for debtor, creds in debts.items():
        for creditor, amount in creds.items():
            if (creditor, debtor) in seen:
                continue
            seen.add((debtor, creditor))
            reverse = debts.get(creditor, {}).get(debtor, 0)
            net = amount - reverse
            if net > 0:
                result[debtor][creditor] = net
            elif net < 0:
                result[creditor][debtor] = -net
    return result


def distribute_payment_amount(
    bills_with_debt: list[tuple[int, int]],
    amount_minor: int,
) -> tuple[list[tuple[int, int]], int]:
    """Greedy-allocate `amount_minor` across bills' outstanding debts in caller-given order.

    `bills_with_debt` is a list of (bill_id, debt_amount_minor); typically sorted FIFO
    so older bills are paid off first. Returns (allocations, residual) where
    `allocations` is a list of (bill_id, allocated_amount) and `residual` is leftover
    overpayment (≥ 0).
    """
    if amount_minor <= 0:
        return [], 0
    allocations: list[tuple[int, int]] = []
    remaining = amount_minor
    for bill_id, debt in bills_with_debt:
        if remaining <= 0:
            break
        if debt <= 0:
            continue
        take = min(debt, remaining)
        allocations.append((bill_id, take))
        remaining -= take
    return allocations, remaining


def apply_payments(
    debts: dict[str, dict[str, int]],
    payments,
    *,
    clamp_zero: bool = False,
) -> dict[str, dict[str, int]]:
    """Subtract confirmed/auto_confirmed payments from debts dict (in-place).

    Refund payments (is_refund=True) flip the effect: they ADD to debt in the
    opposite direction (debt[creditor][debtor]), modelling money flowing back
    from a previous creditor to their previous debtor.
    """
    from steward.data.models.bill_v2 import PaymentStatus
    for p in payments:
        if p.status not in PaymentStatus.SETTLED:
            continue
        if getattr(p, "is_refund", False):
            if p.creditor in debts and p.debtor in debts[p.creditor]:
                debts[p.creditor][p.debtor] += p.amount_minor
        else:
            if p.debtor in debts and p.creditor in debts[p.debtor]:
                debts[p.debtor][p.creditor] -= p.amount_minor
                if clamp_zero and debts[p.debtor][p.creditor] < 0:
                    debts[p.debtor][p.creditor] = 0
    return debts
