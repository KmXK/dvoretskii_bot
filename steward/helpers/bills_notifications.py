"""Notification routing for /bills: find the best Telegram chat to reach a person."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steward.data.models.bill_v2 import BillNotificationPrefs, BillPerson
    from steward.data.models.chat import Chat
    from steward.data.models.user import User


def build_user_ids_in_chats(users: list["User"]) -> dict[int, set[int]]:
    """Return {chat_id: {telegram_id, ...}} from User.chat_ids."""
    result: dict[int, set[int]] = {}
    for user in users:
        for cid in user.chat_ids:
            result.setdefault(cid, set()).add(user.id)
    return result


def _is_quiet(prefs: "BillNotificationPrefs") -> bool:
    """Return True if current time falls in quiet hours."""
    hour = datetime.now().hour
    qs, qe = prefs.quiet_start, prefs.quiet_end
    if qs == 0 and qe == 24:
        return False
    if qs < qe:
        return qs <= hour < qe
    # wraps midnight
    return hour >= qs or hour < qe


def find_best_notification_chat(
    recipient: "BillPerson",
    sender: "BillPerson | None",
    known_chats: list["Chat"],
    user_ids_in_chats: dict[int, set[int]],
    prefs: "BillNotificationPrefs",
    *,
    initiated_chat_id: int | None = None,
    prefer_dm: bool = False,
) -> int | None:
    """Return the best chat_id to send a notification to recipient.

    Priority order:
    1. Check quiet hours first — return None if quiet.
    2. If prefer_dm, the recipient's DM (personal actions like payment
       confirmations shouldn't be dumped into a shared group).
    3. initiated_chat_id (the chat where the action happened) if both are members.
    4. preferred_chat_ids (in order) where both are members.
    5. Any common group chat.
    6. DM as last resort.
    """
    if not recipient.telegram_id:
        return None
    if _is_quiet(prefs):
        return None

    rid = recipient.telegram_id
    sid = sender.telegram_id if sender else None

    def both_present(cid: int) -> bool:
        members = user_ids_in_chats.get(cid, set())
        return rid in members and (sid is None or sid in members)

    dm_chat = next((c for c in known_chats if c.id == rid), None)

    # Personal action: prefer the recipient's DM, falling back to a group
    # (with an inline mention) only when no DM exists.
    if prefer_dm and dm_chat:
        return dm_chat.id

    # 1. initiated_chat_id — where the action happened
    if initiated_chat_id and both_present(initiated_chat_id):
        return initiated_chat_id

    # 2. Preferred chats
    for cid in prefs.preferred_chat_ids:
        if both_present(cid):
            return cid

    # 3. Any common group chat
    for chat in known_chats:
        if chat.id == rid:
            continue
        if both_present(chat.id):
            return chat.id

    # 4. DM as last resort
    if dm_chat:
        return dm_chat.id

    return None


async def send_bill_notification(
    bot,
    repository,
    recipient: "BillPerson",
    text: str,
    *,
    sender: "BillPerson | None" = None,
    reply_markup=None,
    parse_mode: str | None = None,
    initiated_chat_id: int | None = None,
    prefer_dm: bool = False,
):
    """Send a notification to a BillPerson, finding the best chat automatically.

    Set prefer_dm for personal actions (payment confirmations) so they land in
    the recipient's DM instead of a shared group chat.

    Returns the sent Message or None if unreachable.
    """
    if not recipient.telegram_id:
        return None
    recipient_user = next(
        (u for u in repository.db.users if u.id == recipient.telegram_id), None
    )
    if recipient_user is not None and not getattr(
        recipient_user, "bills_notifications_enabled", True
    ):
        return None
    user_ids_in_chats = build_user_ids_in_chats(repository.db.users)
    prefs = repository.get_bill_notification_prefs(recipient.telegram_id)
    chat_id = find_best_notification_chat(
        recipient=recipient,
        sender=sender,
        known_chats=repository.db.chats,
        user_ids_in_chats=user_ids_in_chats,
        prefs=prefs,
        initiated_chat_id=initiated_chat_id,
        prefer_dm=prefer_dm,
    )
    if not chat_id:
        return None
    try:
        return await bot.send_message(
            chat_id=chat_id, text=text,
            reply_markup=reply_markup, parse_mode=parse_mode,
        )
    except Exception:
        return None
