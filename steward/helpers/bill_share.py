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

    def add_item(pid, tx, portion, amount):
        per_person.setdefault(pid, []).append({
            "label": tx.item_name or "—",
            "detail": f"{portion} × {minor_to_display(tx.unit_price_minor, bill.currency)}",
            "amount_minor": amount,
        })

    for tx in bill.transactions:
        assigned_portion = Fraction(0)
        assigned_minor = 0
        for asg in tx.assignments:
            portion = Fraction(asg.unit_count, asg.denominator or 1)
            amount = (
                tx.unit_price_minor * portion.numerator + portion.denominator // 2
            ) // portion.denominator
            assigned_portion += portion
            assigned_minor += amount
            debtors = sorted(asg.debtors, key=lambda pid: pid == tx.creditor)
            if not debtors:
                add_item(UNKNOWN_PERSON_ID, tx, portion, amount)
                continue

            for pid, share in zip(debtors, split_minor(amount, len(debtors))):
                add_item(pid or UNKNOWN_PERSON_ID, tx, portion / len(debtors), share)

        remaining = tx.quantity - assigned_portion
        if remaining > 0:
            add_item(
                UNKNOWN_PERSON_ID,
                tx,
                remaining,
                max(0, tx.unit_price_minor * tx.quantity - assigned_minor),
            )

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
    header = f"🧾 {bill.name or 'Счёт'} — кто что взял\n{summary}"
    sections = [header]
    for group in groups:
        lines = [f"{group['name']} — {group['total']}"]
        lines.extend(
            f"• {item['label']} · {item['detail']} = {item['amount']}"
            for item in group["items"]
        )
        sections.append("\n".join(lines))

    caption = "\n\n".join(sections)
    if len(caption.encode("utf-16-le")) // 2 > 1024:
        title = bill.name or "Счёт"
        suffix = f" — кто что взял\n{summary}\n\nТовары и суммы каждого участника — на картинке."
        available = 1024 - len(f"🧾 {suffix}".encode("utf-16-le")) // 2
        while len(title.encode("utf-16-le")) // 2 > available:
            title = title[:-1]

        if title != (bill.name or "Счёт"):
            title = f"{title[:-1]}…"

        caption = f"🧾 {title}{suffix}"

    return {"groups": groups, "summary": summary, "caption": caption}


def _format_group(name, items, currency):
    return {
        "name": name,
        "total": minor_to_display(sum(item["amount_minor"] for item in items), currency),
        "items": [
            {
                "label": item["label"],
                "detail": item["detail"],
                "amount": minor_to_display(item["amount_minor"], currency),
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
