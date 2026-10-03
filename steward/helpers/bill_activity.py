from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from steward.data.models.bill_v2 import BillActivityChange, BillActivityEvent


bill_activity_actor = ContextVar("bill_activity_actor", default=None)

_BILL_FIELDS = ("name", "currency", "participants", "closed", "distribution_status")
_ITEM_FIELDS = ("item_name", "unit_price_minor", "quantity", "creditor", "assignments")


def snapshot_bills(bills):
    result = {}
    for bill in bills:
        metadata = {name: getattr(bill, name) for name in _BILL_FIELDS}
        metadata["participants"] = list(bill.participants)
        transactions = {}
        for item in bill.transactions:
            transactions[item.id] = {
                "id": item.id,
                "item_name": item.item_name,
                "unit_price_minor": item.unit_price_minor,
                "quantity": item.quantity,
                "creditor": item.creditor,
                "assignments": [
                    {
                        "unit_count": assignment.unit_count,
                        "denominator": assignment.denominator,
                        "debtors": list(assignment.debtors),
                    }
                    for assignment in item.assignments
                ],
            }

        result[bill.id] = {"metadata": metadata, "transactions": transactions}

    return result


def _changed_fields(before, after, fields):
    return [name for name in fields if before.get(name) != after.get(name)]


def _bill_changes(before, after):
    changes = []
    if before is None:
        changes.append(BillActivityChange(kind="created", after=after["metadata"]))
    elif after is None:
        return [BillActivityChange(kind="deleted", before=before["metadata"])]
    else:
        fields = _changed_fields(before["metadata"], after["metadata"], _BILL_FIELDS)
        if fields:
            changes.append(BillActivityChange(
                kind="bill_updated",
                before=before["metadata"],
                after=after["metadata"],
                fields=fields,
            ))

    old_items = before["transactions"] if before else {}
    new_items = after["transactions"]
    for item_id in dict.fromkeys([*old_items, *new_items]):
        old_item = old_items.get(item_id)
        new_item = new_items.get(item_id)
        if old_item is None:
            changes.append(BillActivityChange(kind="item_added", after=new_item))
        elif new_item is None:
            changes.append(BillActivityChange(kind="item_removed", before=old_item))
        else:
            fields = _changed_fields(old_item, new_item, _ITEM_FIELDS)
            if fields:
                changes.append(BillActivityChange(
                    kind="item_updated",
                    before=old_item,
                    after=new_item,
                    fields=fields,
                ))

    return changes


def make_activity_events(before, after, actor_telegram_id=None):
    events = []
    created_at = datetime.now(timezone.utc)
    for bill_id in dict.fromkeys([*before, *after]):
        changes = _bill_changes(before.get(bill_id), after.get(bill_id))
        if changes:
            events.append(BillActivityEvent(
                id=uuid4().hex,
                bill_id=bill_id,
                created_at=created_at,
                actor_telegram_id=actor_telegram_id,
                currency=(after.get(bill_id) or before[bill_id])["metadata"]["currency"],
                changes=changes,
            ))

    return events
