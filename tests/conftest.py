"""Shared test fixtures and helpers."""
# test_repository.py is stale (redacted real IDs, old schema assertions) — skip it
collect_ignore = ["tests/test_repository.py"]

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from telegram import MessageEntity, Update
from telegram.ext import ApplicationBuilder
from telegram.request import BaseRequest

from steward.bot.context import ChatBotContext
from steward.data.repository import Repository, Storage

CHAT_ID = -100123456789
DEFAULT_USER_ID = 12345


# ---------------------------------------------------------------------------
# Telegram API mock
# ---------------------------------------------------------------------------

class MockRequest(BaseRequest):
    """Intercepts Telegram Bot API calls — returns minimal valid responses."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    @property
    def read_timeout(self) -> float:
        return 5.0

    async def do_request(
        self,
        url: str,
        method: str,
        request_data=None,
        **_,
    ) -> tuple[int, bytes]:
        endpoint = url.split("/")[-1]
        params: dict[str, Any] = {}
        if request_data:
            try:
                params = dict(request_data.parameters)
            except Exception:
                pass
        self.calls.append((endpoint, params))

        chat = {"id": CHAT_ID, "type": "group", "title": "Test"}
        msg = {
            "message_id": 1,
            "date": int(time.time()),
            "chat": chat,
            "text": params.get("text", ""),
        }
        results: dict[str, Any] = {
            "getMe": {
                "id": 1,
                "is_bot": True,
                "first_name": "TestBot",
                "username": "testbot",
            },
            "sendMessage": msg,
            "editMessageText": msg,
            "editMessageReplyMarkup": msg,
            "copyMessage": {"message_id": 1},
            "deleteMessage": True,
            "answerCallbackQuery": True,
            "forwardMessage": msg,
        }
        result = results.get(endpoint, True)
        return 200, json.dumps({"ok": True, "result": result}).encode()


# ---------------------------------------------------------------------------
# Async in-memory storage
# ---------------------------------------------------------------------------

class AsyncInMemoryStorage(Storage):
    async def read_dict(self) -> dict:
        return {}

    async def write_dict(self, data: dict):
        pass


def make_repository() -> Repository:
    return Repository(AsyncInMemoryStorage())


# ---------------------------------------------------------------------------
# Bot factory using MockRequest
# ---------------------------------------------------------------------------

_FAKE_TOKEN = "1234567890:AAFabcdefghijklmnopqrstuvwxyz12345"


async def make_bot(mock_request: MockRequest | None = None):
    """Create a real PTB Bot backed by MockRequest (no network calls)."""
    req = mock_request or MockRequest()
    app = (
        ApplicationBuilder()
        .token(_FAKE_TOKEN)
        .request(req)
        .updater(None)
        .build()
    )
    await app.initialize()
    return app.bot, app


# ---------------------------------------------------------------------------
# Context factories
# ---------------------------------------------------------------------------

def _make_message_mock(
    text: str,
    is_command: bool,
    user_id: int,
    bot_username: str = "testbot",
    chat_id: int = CHAT_ID,
) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.chat.type = "group"
    message.chat.id = chat_id
    message.chat_id = chat_id
    message.from_user.id = user_id
    message.from_user.username = "testuser"
    message.from_user.name = "testuser"
    message.from_user.first_name = "Test"
    message.message_id = 1
    message.forward_origin = None

    if is_command:
        entity = MagicMock()
        entity.type = MessageEntity.BOT_COMMAND
        entity.offset = 0
        entity.length = len(text.split()[0])
        message.entities = [entity]
        bot_mock = MagicMock()
        bot_mock.username = bot_username
        message.get_bot.return_value = bot_mock
    else:
        message.entities = []

    for method in (
        "reply_text", "reply_html", "reply_markdown", "reply_markdown_v2",
        "reply_photo", "reply_animation", "reply_document", "reply_video",
        "reply_audio", "reply_sticker", "delete", "edit_text",
    ):
        setattr(message, method, AsyncMock(return_value=MagicMock()))

    return message


def make_update(
    command: str,
    args: str = "",
    bot_username: str = "testbot",
    user_id: int = DEFAULT_USER_ID,
    chat_id: int = CHAT_ID,
) -> MagicMock:
    """Create a mock Update for a bot command."""
    cmd_text = f"/{command}"
    full_text = cmd_text + (f" {args}" if args else "")
    message = _make_message_mock(
        full_text,
        is_command=True,
        user_id=user_id,
        bot_username=bot_username,
        chat_id=chat_id,
    )

    update = MagicMock(spec=Update)
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.message = message
    update.edited_message = None
    update.callback_query = None

    return update


def make_text_update(text: str, user_id: int = DEFAULT_USER_ID, chat_id: int = CHAT_ID) -> MagicMock:
    """Create a mock Update for a plain (non-command) text message."""
    message = _make_message_mock(text, is_command=False, user_id=user_id, chat_id=chat_id)

    update = MagicMock(spec=Update)
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.message = message
    update.edited_message = None
    update.callback_query = None

    return update


def get_reply_text(mock_method) -> str:
    """Extract text from reply_text / reply_html call regardless of positional/keyword."""
    call = mock_method.call_args
    if call is None:
        return ""
    return call.args[0] if call.args else call.kwargs.get("text", "")


def make_context(
    command: str,
    args: str = "",
    repo: Repository | None = None,
    bot=None,
    user_id: int = DEFAULT_USER_ID,
    metrics=None,
    chat_id: int = CHAT_ID,
) -> ChatBotContext:
    update = make_update(command, args, user_id=user_id, chat_id=chat_id)
    return ChatBotContext(
        repository=repo or make_repository(),
        bot=bot or MagicMock(),
        client=MagicMock(),
        update=update,
        tg_context=MagicMock(),
        metrics=metrics or MagicMock(),
        message=update.message,
    )


def make_text_context(
    text: str,
    repo: Repository | None = None,
    user_id: int = DEFAULT_USER_ID,
    metrics=None,
    chat_id: int = CHAT_ID,
) -> ChatBotContext:
    """Create a context for a plain non-command text message (used in multi-step flows)."""
    update = make_text_update(text, user_id=user_id, chat_id=chat_id)
    return ChatBotContext(
        repository=repo or make_repository(),
        bot=MagicMock(),
        client=MagicMock(),
        update=update,
        tg_context=MagicMock(),
        metrics=metrics or MagicMock(),
        message=update.message,
    )


async def invoke(
    handler_class,
    text: str,
    repo: Repository,
    user_id: int = DEFAULT_USER_ID,
    metrics=None,
    chat_id: int = CHAT_ID,
) -> tuple[str, bool]:
    """Invoke handler.chat() with the given command text and return (reply, handled)."""
    stripped = text.lstrip("/")
    parts = stripped.split(None, 1)
    command = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    handler = handler_class()
    handler.repository = repo
    handler.bot = MagicMock()

    ctx = make_context(command, args=args, repo=repo, user_id=user_id, metrics=metrics, chat_id=chat_id)
    result = await handler.chat(ctx)

    for method_name in ("reply_text", "reply_html", "reply_markdown", "reply_markdown_v2"):
        reply = get_reply_text(getattr(ctx.message, method_name))
        if reply:
            return reply, bool(result)

    return "", bool(result)
