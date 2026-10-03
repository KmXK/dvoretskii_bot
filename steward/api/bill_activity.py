from dataclasses import asdict

from aiohttp import web

from steward.api.auth import session_user_id
from steward.helpers.bill_activity import bill_activity_actor


@web.middleware
async def activity_actor_middleware(request, handler):
    token = bill_activity_actor.set(session_user_id(request))
    try:
        return await handler(request)
    finally:
        bill_activity_actor.reset(token)


def serialize_bill_activity(event, repository):
    actor = repository.get_bill_person_by_telegram_id(event.actor_telegram_id) if event.actor_telegram_id is not None else None
    user = next((user for user in repository.db.users if user.id == event.actor_telegram_id), None)
    actor_name = actor.display_name if actor else (user.username or user.first_name if user else None)
    return {
        "id": event.id,
        "date": event.created_at.isoformat(),
        "actor": actor_name,
        "currency": event.currency,
        "changes": [asdict(change) for change in event.changes],
    }
