from collections import defaultdict
from dataclasses import replace
from datetime import timezone

from steward.data.models.bill_v2 import PaymentStatus
from steward.helpers.bills_money import compute_bill_balances, compute_bill_debts, net_debts


def _timestamp(value):
    if value is None:
        return float("inf")

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.timestamp()


def _date(value):
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.isoformat()


def _pair_balances(bills, payments):
    balances, credits = compute_bill_balances(bills, payments)
    result = defaultdict(int)
    for bill in bills:
        for debtor, creditors in balances.get(bill.id, {}).items():
            for creditor, amount in creditors.items():
                result[debtor, creditor, bill.currency] += amount

    for key, amount in credits.items():
        result[key] -= amount

    return dict(result)


def _bill_amounts(bill):
    return {
        (debtor, creditor, bill.currency): amount
        for debtor, creditors in net_debts(compute_bill_debts(bill.transactions)).items()
        for creditor, amount in creditors.items()
    }


def _bill_reference(bill):
    return {"id": bill.id, "name": bill.name, "closed": bill.closed}


def _transaction_date(bill, transaction):
    date = transaction.created_at
    if transaction.source == "sheet" or date is None:
        return bill.created_at

    if bill.updated_at and _timestamp(date) > _timestamp(bill.updated_at):
        return bill.created_at

    if bill.closed_at and _timestamp(date) > _timestamp(bill.closed_at):
        return bill.created_at

    if _timestamp(date) < _timestamp(bill.created_at):
        return bill.created_at

    return date


def _bill_charge_operations(bill):
    groups = {_timestamp(bill.created_at): {"date": bill.created_at, "transactions": []}}
    for transaction in bill.transactions:
        date = _transaction_date(bill, transaction)
        group = groups.setdefault(_timestamp(date), {"date": date, "transactions": []})
        group["transactions"].append(transaction)

    cumulative = []
    previous = {}
    operations = []
    for index, (_, group) in enumerate(sorted(groups.items())):
        cumulative.extend(group["transactions"])
        current = _bill_amounts(replace(bill, transactions=cumulative)) if bill.distribution_status == "final" else {}
        operations.append({
            "id": f"bill:{bill.id}:{index}",
            "type": "charge",
            "date": group["date"],
            "bill": bill,
            "transactions": group["transactions"],
            "amounts": {
                key: current.get(key, 0) - previous.get(key, 0)
                for key in set(current) | set(previous)
            },
            "bills": [_bill_reference(bill)],
        })
        previous = current

    return operations


def _operation_items(operation, debtor, creditor):
    items = []
    for transaction in operation.get("transactions", []):
        debts = compute_bill_debts([transaction])
        amount = debts.get(debtor, {}).get(creditor, 0) - debts.get(creditor, {}).get(debtor, 0)
        if amount:
            items.append({"name": transaction.item_name or "—", "amount_minor": amount})

    return items


def _history_operations(bills, payments):
    operations = []
    for bill in bills:
        operations.extend(_bill_charge_operations(bill))
        if bill.closed:
            operations.append({
                "id": f"close:{bill.id}",
                "type": "close",
                "date": bill.closed_at,
                "bill": bill,
                "amounts": _bill_amounts(bill) if bill.closed_at is None and bill.distribution_status == "final" else {},
                "bills": [_bill_reference(bill)],
            })

    bills_by_id = {bill.id: bill for bill in bills}
    grouped_payments = {}
    for index, payment in enumerate(payments):
        if payment.status not in PaymentStatus.SETTLED:
            continue

        date = payment.settled_at or payment.created_at
        pair = (payment.debtor, payment.creditor, payment.currency)
        key = (pair, _date(date), _date(payment.created_at), payment.is_refund)
        if payment.is_refund and payment.bill_ids:
            pair = (payment.creditor, payment.debtor, payment.currency)

        group = grouped_payments.setdefault(key, {
            "id": f"payment:{payment.id}",
            "type": "adjustment" if payment.is_refund else "payment",
            "date": date,
            "payments": [],
            "amounts": {pair: 0},
            "bills": [],
        })
        group["payments"].append(index)
        group["amounts"][pair] += payment.amount_minor
        known_ids = {bill["id"] for bill in group["bills"]}
        group["bills"].extend(
            _bill_reference(bills_by_id[bill_id])
            for bill_id in payment.bill_ids
            if bill_id in bills_by_id and bill_id not in known_ids
        )

    operations.extend(grouped_payments.values())
    priorities = {"charge": 0, "payment": 1, "adjustment": 1, "close": 2}
    return sorted(
        operations,
        key=lambda operation: (
            _timestamp(operation["date"]),
            priorities[operation["type"]],
            operation["id"],
        ),
    )


def build_debt_history(bills, payments, person_id):
    active_bills = {}
    included_payments = set()
    before = {}
    events = []
    for operation in _history_operations(bills, payments):
        kind = operation["type"]
        if kind == "charge":
            bill = operation["bill"]
            previous_transactions = active_bills[bill.id].transactions if bill.id in active_bills else []
            active_bills[bill.id] = replace(
                bill,
                transactions=previous_transactions + operation["transactions"],
                closed=bill.closed and bill.closed_at is None,
                closed_at=None,
            )
        elif kind == "close":
            bill = operation["bill"]
            active_bills[bill.id] = replace(bill)
        else:
            included_payments.update(operation["payments"])

        current_payments = [
            payment
            for index, payment in enumerate(payments)
            if index in included_payments
        ]
        after = _pair_balances(list(active_bills.values()), current_payments)
        keys = set(before) | set(after) | set(operation["amounts"])
        for key in sorted(keys):
            debtor, creditor, currency = key
            if person_id not in (debtor, creditor):
                continue

            old_amount = before.get(key, 0)
            new_amount = after.get(key, 0)
            amount = operation["amounts"].get(key, 0)
            if old_amount == new_amount and not amount:
                continue

            events.append({
                "id": f"{operation['id']}:{debtor}:{creditor}:{currency}",
                "type": kind,
                "date": _date(operation["date"]),
                "debtor": debtor,
                "creditor": creditor,
                "currency": currency,
                "amount_minor": amount,
                "before_minor": old_amount,
                "delta_minor": new_amount - old_amount,
                "after_minor": new_amount,
                "items": _operation_items(operation, debtor, creditor),
                "balance_known": not (
                    kind in ("charge", "close")
                    and operation["bill"].closed
                    and operation["bill"].closed_at is None
                ),
                "bills": operation["bills"],
            })

        before = after

    balances = [
        {"debtor": debtor, "creditor": creditor, "currency": currency, "amount_minor": amount}
        for (debtor, creditor, currency), amount in sorted(before.items())
        if amount and person_id in (debtor, creditor)
    ]
    return {"events": list(reversed(events)), "balances": balances}
