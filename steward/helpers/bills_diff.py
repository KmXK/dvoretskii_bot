"""Diff snapshots and change notifications for /bills."""
from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steward.data.models.bill_v2 import BillV2
    from steward.data.repository import Repository


def store_diff_snapshot(
    repository: "Repository",
    bill_id: int,
    before: "BillV2 | None",
    after: "BillV2 | None",
) -> str:
    from steward.data.models.bill_v2 import BillDiffSnapshot

    token = str(uuid.uuid4())
    snapshot = BillDiffSnapshot(
        token=token,
        bill_id=bill_id,
        before=asdict(before) if before else {},
        after=asdict(after) if after else {},
    )
    repository.db.bill_diff_snapshots.append(snapshot)
    repository.cleanup_expired_diff_snapshots()
    return token


def compute_debt_delta(
    before: "BillV2 | None",
    after: "BillV2 | None",
    person_id: str,
) -> dict[str, int]:
    """Return {other_person_id: delta_minor} of debt changes for person_id."""
    from steward.helpers.bills_money import compute_bill_debts

    def _debts_for(bill: "BillV2 | None") -> dict[str, int]:
        if bill is None:
            return {}
        all_debts = compute_bill_debts(bill.transactions, bill.currency)
        result: dict[str, int] = {}
        for debtor, creds in all_debts.items():
            for creditor, amt in creds.items():
                if debtor == person_id:
                    result[creditor] = result.get(creditor, 0) + amt
                if creditor == person_id:
                    result[debtor] = result.get(debtor, 0) - amt
        return result

    before_debts = _debts_for(before)
    after_debts = _debts_for(after)
    all_ids = set(before_debts) | set(after_debts)
    delta = {
        other: after_debts.get(other, 0) - before_debts.get(other, 0)
        for other in all_ids
        if abs(after_debts.get(other, 0) - before_debts.get(other, 0)) >= 1
    }
    return delta


async def build_change_notification(
    person_id: str,
    person_name: str,
    delta: dict[str, int],
    person_name_map: dict[str, str],
    bill_name: str,
    diff_token: str,
    diff_base_url: str = "",
) -> str | None:
    """Generate a short AI-powered change notification for a person.

    Returns None if there are no meaningful changes.
    """
    if not delta:
        return None

    from steward.helpers.bills_money import minor_to_display

    changes_text = ""
    for other_id, diff_minor in delta.items():
        other_name = person_name_map.get(other_id, other_id)
        if diff_minor > 0:
            changes_text += f"Ты должен {other_name} +{minor_to_display(diff_minor)}\n"
        else:
            changes_text += f"{other_name} должен тебе +{minor_to_display(-diff_minor)}\n"

    try:
        from steward.helpers.ai import make_yandex_ai_query, YandexModelTypes
        prompt = (
            f'Счёт «{bill_name}» изменился. Для {person_name} изменения:\n{changes_text}\n'
            "Напиши одно короткое дружеское сообщение (1–2 предложения, без лишних слов), "
            "которое объяснит этому человеку что именно изменилось для него лично. "
            "Используй неформальный русский язык."
        )
        summary = await make_yandex_ai_query(
            user_id="bills_diff",
            messages=[("user", prompt)],
            model=YandexModelTypes.YANDEXGPT_5_PRO,
        )
        if summary:
            summary = summary.strip()
        else:
            summary = f"Счёт «{bill_name}» обновился:\n{changes_text.strip()}"
    except Exception:
        summary = f"Счёт «{bill_name}» обновился:\n{changes_text.strip()}"

    if diff_base_url and diff_token:
        url = f"{diff_base_url}/bills/diff/{diff_token}"
        return f"{summary} [подробнее]({url})"
    return summary


async def build_payment_reminder_phrase(
    debtor_name: str,
    creditor_name: str,
    amount_minor: int,
    currency: str = "BYN",
) -> str:
    """Generate a short funny reminder phrase for payment confirmation."""
    from steward.helpers.bills_money import minor_to_display

    amount_str = minor_to_display(amount_minor, currency)
    try:
        from steward.helpers.ai import make_yandex_ai_query, YandexModelTypes
        prompt = (
            f"{debtor_name} должен был подтвердить получение {amount_str} от {creditor_name}, "
            "но не ответил уже 8 часов. Напиши одну смешную фразу-напоминалку "
            "на неформальном русском языке, не более 15 слов."
        )
        phrase = await make_yandex_ai_query(
            user_id="bills_reminder",
            messages=[("user", prompt)],
            model=YandexModelTypes.YANDEXGPT_5_PRO,
        )
        return (phrase or "").strip() or "Эй, подтверди уже получение!"
    except Exception:
        return "Эй, подтверди уже получение!"
