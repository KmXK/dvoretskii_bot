from fractions import Fraction

from steward.data.models.bill_v2 import UNKNOWN_PERSON_ID
from steward.helpers.bills_money import minor_to_display, split_minor


def build_bill_share(bill, names: dict[str, str]) -> dict:
    per_person = {
        pid: []
        for pid in bill.participants
        if pid and pid != UNKNOWN_PERSON_ID
    }
    total_minor = sum(tx.unit_price_minor * tx.quantity for tx in bill.transactions)

    for tx in bill.transactions:
        assigned_portion = Fraction(0)
        assigned_minor = 0
        allocations = {}
        for asg in tx.assignments:
            portion = Fraction(asg.unit_count, asg.denominator or 1)
            amount = (
                tx.unit_price_minor * portion.numerator + portion.denominator // 2
            ) // portion.denominator
            assigned_portion += portion
            assigned_minor += amount
            debtors = sorted(asg.debtors, key=lambda pid: pid == tx.creditor)
            if not debtors:
                _add_portion(allocations, UNKNOWN_PERSON_ID, portion, amount)
                continue

            for pid, share in zip(debtors, split_minor(amount, len(debtors))):
                _add_portion(allocations, pid or UNKNOWN_PERSON_ID, portion / len(debtors), share)

        remaining = tx.quantity - assigned_portion
        if remaining > 0:
            _add_portion(
                allocations,
                UNKNOWN_PERSON_ID,
                remaining,
                max(0, tx.unit_price_minor * tx.quantity - assigned_minor),
            )

        for pid, (portion, amount) in allocations.items():
            per_person.setdefault(pid, []).append(_format_item(tx, portion, amount, bill.currency))

    groups = []
    for pid in sorted(per_person, key=lambda pid: names.get(pid, "").lower()):
        if pid == UNKNOWN_PERSON_ID:
            continue

        groups.append(_format_group(names.get(pid, "?"), per_person[pid], bill.currency))

    people_count = len(groups)
    if UNKNOWN_PERSON_ID in per_person:
        groups.append(_format_group("Не распределено", per_person[UNKNOWN_PERSON_ID], bill.currency))

    rounding_minor = total_minor - sum(
        item["amount_minor"]
        for items in per_person.values()
        for item in items
    )
    if rounding_minor:
        groups.append({
            "name": "Разница округления",
            "total": minor_to_display(rounding_minor, bill.currency),
            "items": [],
        })

    total = minor_to_display(total_minor, bill.currency)
    summary = f"{people_count} {_people_word(people_count)} · итого {total}"
    return {"groups": groups, "summary": summary}


def _add_portion(allocations, pid, portion, amount):
    old_portion, old_amount = allocations.get(pid, (Fraction(0), 0))
    allocations[pid] = (old_portion + portion, old_amount + amount)


def _format_item(transaction, portion, amount, currency):
    share = portion / max(transaction.quantity, 1)
    fraction = f"{share.numerator}/{share.denominator}"
    total_minor = transaction.unit_price_minor * transaction.quantity
    total = minor_to_display(total_minor, currency)
    sign = "=" if share * total_minor == amount else "≈"
    result = {
        "label": transaction.item_name or "—",
        "detail": f"{fraction} × {total} {sign} {minor_to_display(amount, currency)}",
        "amount_minor": amount,
    }
    if transaction.quantity > 1:
        price = minor_to_display(transaction.unit_price_minor, currency)
        result["quantity_detail"] = f"Вся позиция: {transaction.quantity} × {price} = {total}"

    return result


def _format_group(name, items, currency):
    return {
        "name": name,
        "total": minor_to_display(sum(item["amount_minor"] for item in items), currency),
        "items": [
            {
                "label": item["label"],
                "detail": item["detail"],
                "amount": minor_to_display(item["amount_minor"], currency),
                **({"quantity_detail": item["quantity_detail"]} if "quantity_detail" in item else {}),
            }
            for item in items
        ],
    }


def _people_word(count):
    if count % 10 == 1 and count % 100 != 11:
        return "участник"

    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "участника"

    return "участников"
