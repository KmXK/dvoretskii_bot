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
            # This row covers unit_count/denominator units of the item. Round the
            # row's cost to whole minor units half-up so per-row totals reconcile
            # with the position cost within a kopeck.
            den = getattr(asg, "denominator", 1) or 1
            asg_total = (tx.unit_price_minor * asg.unit_count + den // 2) // den
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


def compute_bill_balances(
    bills,
    payments,
) -> tuple[dict[int, dict[str, dict[str, int]]], dict[tuple[str, str, str], int]]:
    from steward.data.models.bill_v2 import PaymentStatus

    ordered_bills = sorted(bills, key=lambda bill: (bill.created_at, bill.id))
    bills_by_id = {bill.id: bill for bill in ordered_bills}
    balances: dict[int, dict[str, dict[str, int]]] = {
        bill.id: net_debts(compute_bill_debts(bill.transactions, bill.currency))
        for bill in ordered_bills
    }
    credits: dict[tuple[str, str, str], int] = {}

    for payment in payments:
        if payment.status not in PaymentStatus.SETTLED:
            continue

        currency = getattr(payment, "currency", "BYN")
        credit_key = (payment.debtor, payment.creditor, currency)
        matching_bill_ids = [
            bill_id
            for bill_id in payment.bill_ids
            if bill_id in bills_by_id and bills_by_id[bill_id].currency == currency
        ]
        if payment.bill_ids and not matching_bill_ids:
            continue

        if getattr(payment, "is_refund", False):
            remaining = payment.amount_minor
            available = credits.get(credit_key, 0)
            used = min(available, remaining)
            if used:
                credits[credit_key] = available - used
                remaining -= used

            if remaining:
                target_ids = matching_bill_ids
                if not target_ids:
                    target_ids = [
                        bill.id
                        for bill in ordered_bills
                        if not bill.closed and bill.currency == currency
                    ]
                if target_ids:
                    target = balances.get(target_ids[0])
                    if target is not None:
                        target.setdefault(payment.creditor, {})
                        target[payment.creditor][payment.debtor] = (
                            target[payment.creditor].get(payment.debtor, 0) + remaining
                        )
            continue

        remaining = payment.amount_minor
        for bill_id in matching_bill_ids:
            debt = balances[bill_id].get(payment.debtor, {}).get(payment.creditor, 0)
            applied = min(max(debt, 0), remaining)
            if applied:
                balances[bill_id][payment.debtor][payment.creditor] -= applied
                remaining -= applied
            if remaining == 0:
                break

        if remaining:
            credits[credit_key] = credits.get(credit_key, 0) + remaining

    for bill in ordered_bills:
        if bill.closed or getattr(bill, "distribution_status", "final") != "final":
            balances[bill.id] = {}
            continue

        balance = balances[bill.id]
        for (debtor, creditor, currency), amount in list(credits.items()):
            if amount <= 0 or bill.currency != currency:
                continue

            debt = balance.get(debtor, {}).get(creditor, 0)
            applied = min(max(debt, 0), amount)
            if applied:
                balance[debtor][creditor] -= applied
                credits[(debtor, creditor, currency)] -= applied

        balances[bill.id] = net_debts(balance)

    return balances, {key: amount for key, amount in credits.items() if amount > 0}
