import datetime
import logging
from aiohttp import web

from steward.data.models.feature_request import (
    FeatureRequest,
    FeatureRequestChange,
    FeatureRequestStatus,
)
from steward.data.repository import Repository

logger = logging.getLogger(__name__)


def serialize_army(army):
    now = datetime.datetime.now()
    end = datetime.datetime.fromtimestamp(army.end_date)
    start = datetime.datetime.fromtimestamp(army.start_date)
    remaining = (end - now).total_seconds()
    total = (end - start).total_seconds()
    percent = max(0.0, min(1.0, 1 - remaining / total)) if total > 0 else 1.0
    return {
        "name": army.name,
        "start_date": army.start_date,
        "end_date": army.end_date,
        "remaining_seconds": max(0, remaining),
        "percent": percent,
        "done": remaining <= 0,
    }


async def handle_army(request: web.Request):
    repository: Repository = request.app["repository"]
    items = sorted(repository.db.army, key=lambda a: (a.end_date, a.start_date))
    return web.json_response([serialize_army(a) for a in items])


def serialize_todo(item):
    return {
        "id": item.id,
        "chat_id": item.chat_id,
        "text": item.text,
        "is_done": item.is_done,
    }


async def handle_todos(request: web.Request):
    repository: Repository = request.app["repository"]
    return web.json_response(
        [serialize_todo(t) for t in repository.db.todo_items]
    )


async def handle_todo_toggle(request: web.Request):
    repository: Repository = request.app["repository"]
    todo_id = int(request.match_info["id"])
    todo = next((t for t in repository.db.todo_items if t.id == todo_id), None)
    if not todo:
        return web.json_response({"error": "not found"}, status=404)
    todo.is_done = not todo.is_done
    await repository.save()
    return web.json_response(serialize_todo(todo))


def serialize_feature_request(fr):
    return {
        "id": fr.id,
        "text": fr.text,
        "author_id": fr.author_id,
        "author_name": fr.author_name,
        "status": int(fr.status),
        "creation_timestamp": fr.creation_timestamp,
        "priority": fr.priority,
        "notes": fr.notes,
        "history": [
            {
                "status": int(c.status),
                "timestamp": c.timestamp,
            }
            for c in fr.history
        ],
    }


async def handle_feature_requests(request: web.Request):
    repository: Repository = request.app["repository"]
    return web.json_response(
        [serialize_feature_request(fr) for fr in repository.db.feature_requests]
    )


async def handle_feature_request_detail(request: web.Request):
    repository: Repository = request.app["repository"]
    fr_id = int(request.match_info["id"])

    if fr_id <= 0 or fr_id > len(repository.db.feature_requests):
        return web.json_response({"error": "not found"}, status=404)

    fr = repository.db.feature_requests[fr_id - 1]
    return web.json_response(serialize_feature_request(fr))


async def handle_feature_request_update(request: web.Request):
    repository: Repository = request.app["repository"]
    fr_id = int(request.match_info["id"])

    if fr_id <= 0 or fr_id > len(repository.db.feature_requests):
        return web.json_response({"error": "not found"}, status=404)

    fr = repository.db.feature_requests[fr_id - 1]
    body = await request.json()

    if "status" in body:
        new_status = int(body["status"])
        if new_status not in [s.value for s in FeatureRequestStatus]:
            return web.json_response({"error": "invalid status"}, status=400)
        if int(fr.status) != new_status:
            fr.history.append(
                FeatureRequestChange(
                    author_id=0,
                    timestamp=datetime.datetime.now().timestamp(),
                    message_id=0,
                    status=FeatureRequestStatus(new_status),
                )
            )

    if "priority" in body:
        priority = int(body["priority"])
        if priority < 1 or priority > 5:
            return web.json_response({"error": "priority must be 1-5"}, status=400)
        fr.priority = priority

    if "note" in body:
        note = str(body["note"]).strip()
        if note:
            fr.notes.append(note)

    await repository.save()
    return web.json_response(serialize_feature_request(fr))


async def handle_feature_request_create(request: web.Request):
    repository: Repository = request.app["repository"]
    body = await request.json()

    text = str(body.get("text", "")).strip()
    if not text:
        return web.json_response({"error": "text is required"}, status=400)

    author_name = str(body.get("author_name", "Web")).strip()

    fr = FeatureRequest(
        id=len(repository.db.feature_requests) + 1,
        text=text,
        author_id=0,
        author_name=author_name,
        creation_timestamp=datetime.datetime.now().timestamp(),
        message_id=None,
        chat_id=None,
    )
    repository.db.feature_requests.append(fr)
    await repository.save()
    return web.json_response(serialize_feature_request(fr), status=201)


async def start_api_server(repository: Repository, port: int = 8080):
    app = web.Application()
    app["repository"] = repository
    app.router.add_get("/api/army", handle_army)
    app.router.add_get("/api/todos", handle_todos)
    app.router.add_patch("/api/todos/{id}", handle_todo_toggle)
    app.router.add_get("/api/feature-requests", handle_feature_requests)
    app.router.add_post("/api/feature-requests", handle_feature_request_create)
    app.router.add_get("/api/feature-requests/{id}", handle_feature_request_detail)
    app.router.add_patch("/api/feature-requests/{id}", handle_feature_request_update)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"API server started on port {port}")
