from inspect import isawaitable
from time import time
from typing import AsyncIterator, Awaitable, Callable

import telethon
from async_lru import alru_cache
from telegram import Message
from telethon import TelegramClient

import asyncio

from steward.bot.context import ChatBotContext
from steward.data.models.ai_message import AiMessage
from steward.helpers.tg_streaming import stream_reply
from steward.helpers.thinking import try_contextual_placeholder
from steward.helpers.user_language import language_prompt_for
from steward.helpers.user_memory import (
    add_facts,
    extract_facts_via_ai,
    format_facts_for_prompt,
    get_recent_facts,
    prune_expired,
)

type AiCallable = Callable[[int, list[tuple[str, str]]], str | Awaitable[str]]
type AiStreamCallable = Callable[
    [int, list[tuple[str, str]]],
    AsyncIterator[str] | Awaitable[AsyncIterator[str]],
]

type QuickCallable = Callable[[str], str | Awaitable[str]]
type PostProcessCallable = Callable[
    [Message, str], Awaitable[None] | None
]

_ai_handlers: dict[str, AiCallable] = {}
_ai_stream_handlers: dict[str, AiStreamCallable] = {}
_ai_quick_handlers: dict[str, QuickCallable] = {}

# Grok tends to glue a meta-comment / rhetorical filler onto the end of a reply
# ("а что хотел то", "ну как-то так", …). Inject this into every persona's
# context so the model ends on substance instead. Applies to all callers of the
# execute_ai_request* helpers (the /ai butler, Diana, Pasha).
NO_META_TAIL_HINT = (
    "Заканчивай ответ строго по существу. Не добавляй в конце никаких приписок, "
    "подытоживаний и риторических вопросов-затычек вроде «а что хотел то», "
    "«ну как-то так», «вот так вот», «что ещё хотел узнать» и подобных "
    "мета-комментариев — последняя фраза должна быть содержательной частью "
    "самого ответа."
)


def register_ai_handler(
    name: str,
    call: AiCallable,
    stream_call: AiStreamCallable | None = None,
    quick_call: QuickCallable | None = None,
):
    _ai_handlers[name] = call
    if stream_call is not None:
        _ai_stream_handlers[name] = stream_call
    if quick_call is not None:
        _ai_quick_handlers[name] = quick_call


def get_ai_handler(name: str) -> AiCallable | None:
    return _ai_handlers.get(name)


def get_ai_stream_handler(name: str) -> AiStreamCallable | None:
    return _ai_stream_handlers.get(name)


def get_ai_quick_handler(name: str) -> QuickCallable | None:
    return _ai_quick_handlers.get(name)


@alru_cache(1024)
async def _get_message_by_id(tg_client: TelegramClient, chat_id, message_id):
    message = await tg_client.get_messages(chat_id, ids=message_id)
    assert message is None or isinstance(message, telethon.types.Message)
    return message


async def build_reply_context(context: ChatBotContext, text: str) -> list[tuple[str, str]]:
    result = []

    message = await _get_message_by_id(
        context.client,
        context.message.chat.id,
        context.message.id,
    )

    result.append(("user", text))

    while message:
        reply_to_msg_id = 0
        if message.reply_to and message.reply_to.reply_to_msg_id:
            reply_to_msg_id = message.reply_to.reply_to_msg_id
        elif (
            f"{context.message.chat.id}_{message.id}"
            in context.repository.db.ai_messages
        ):
            reply_to_msg_id = context.repository.db.ai_messages[
                f"{context.message.chat.id}_{message.id}"
            ].message_id

        if reply_to_msg_id == 0:
            break

        message = await _get_message_by_id(
            context.client,
            context.message.chat.id,
            reply_to_msg_id,
        )

        if message and message.message:
            if message.from_id and message.from_id.user_id == context.bot.id:
                result.append(("assistant", message.message))
            else:
                result.append(("user", message.message))

    return [*reversed(result)]


async def execute_ai_request(
    context: ChatBotContext,
    text: str,
    ai_call: AiCallable,
    handler_name: str,
):
    messages = await build_reply_context(context, text)
    language_hint = language_prompt_for(
        context.repository, context.message.from_user.id
    )
    if language_hint:
        messages = [("system", language_hint), *messages]
    messages = [("system", NO_META_TAIL_HINT), *messages]
    response = ai_call(context.message.from_user.id, messages)
    if isawaitable(response):
        response = await response

    bot_message = await context.message.reply_markdown(response)

    context.repository.db.ai_messages[
        f"{context.message.chat.id}_{bot_message.id}"
    ] = AiMessage(time(), context.message.id, handler_name)

    if len(context.repository.db.ai_messages) > 1000:
        oldest = min(
            context.repository.db.ai_messages,
            key=lambda k: context.repository.db.ai_messages[k].timestamp,
        )
        del context.repository.db.ai_messages[oldest]
    await context.repository.save()


async def execute_ai_request_streaming(
    context: ChatBotContext,
    text: str,
    ai_stream_call: AiStreamCallable,
    handler_name: str,
    *,
    quick_call: Callable[[str], str | Awaitable[str]] | None = None,
    placeholder_upgrade: Awaitable[str | None] | None = None,
    post_process: PostProcessCallable | None = None,
):
    """Same shape as execute_ai_request, but streams tokens into the Telegram
    message as they arrive. When `quick_call` is given:
      - A random placeholder shows immediately; a topic-aware one hot-swaps
        in when the fast model replies.
      - Facts about the user (extracted from past messages) are injected as
        an extra system message into the main model's context.
      - After the reply, the user's latest message is quietly analysed in
        the background for new facts to remember.

    `placeholder_upgrade` overrides the default contextual-placeholder task.
    Pass it when the caller already knows what kind of phrase to show (e.g.
    a "going online" hint when routing through web-search).

    `post_process(bot_message, full_text)` is invoked after the stream
    finishes; subclasses can use it to inspect/rewrite the sent message
    (e.g. content-filter substitutions for Pasha's Yandex denial phrase).

    Persists the final message the same way."""
    user_id = context.message.from_user.id
    user_name = context.message.from_user.full_name or context.message.from_user.username

    messages = await build_reply_context(context, text)

    prune_expired(context.repository)
    facts = get_recent_facts(context.repository, user_id)
    if facts:
        memory_block = format_facts_for_prompt(user_id, user_name, facts)
        if memory_block:
            messages = [("system", memory_block), *messages]

    language_hint = language_prompt_for(context.repository, user_id)
    if language_hint:
        messages = [("system", language_hint), *messages]

    messages = [("system", NO_META_TAIL_HINT), *messages]

    upgrade_task: asyncio.Task[str | None] | None = None
    if placeholder_upgrade is not None:
        upgrade_task = asyncio.create_task(_await_awaitable(placeholder_upgrade))
    elif quick_call is not None:
        upgrade_task = asyncio.create_task(
            try_contextual_placeholder(text, quick_call)
        )

    captured: list[str] = []
    stream_for_reply = ai_stream_call(user_id, messages)
    if post_process is not None:
        stream_for_reply = _captured_stream(stream_for_reply, captured)

    try:
        # If stream is an awaitable, let stream_reply resolve it AFTER sending
        # the placeholder — this keeps the placeholder reply instant even when
        # stream init (classifier, web search, etc.) takes seconds.
        bot_message = await stream_reply(
            context.message,
            stream_for_reply,
            placeholder_upgrade=upgrade_task,
        )
    finally:
        if upgrade_task is not None and not upgrade_task.done():
            upgrade_task.cancel()

    if post_process is not None:
        result = post_process(bot_message, "".join(captured))
        if isawaitable(result):
            await result

    if quick_call is not None:
        asyncio.create_task(
            _remember_facts_bg(context.repository, user_id, text, quick_call)
        )

    context.repository.db.ai_messages[
        f"{context.message.chat.id}_{bot_message.id}"
    ] = AiMessage(time(), context.message.id, handler_name)

    if len(context.repository.db.ai_messages) > 1000:
        oldest = min(
            context.repository.db.ai_messages,
            key=lambda k: context.repository.db.ai_messages[k].timestamp,
        )
        del context.repository.db.ai_messages[oldest]
    await context.repository.save()


async def _captured_stream(
    source: AsyncIterator[str] | Awaitable[AsyncIterator[str]],
    sink: list[str],
) -> AsyncIterator[str]:
    if isawaitable(source):
        source = await source
    async for chunk in source:
        sink.append(chunk)
        yield chunk


async def _await_awaitable(awaitable: Awaitable[str | None]) -> str | None:
    return await awaitable


async def _remember_facts_bg(
    repository,
    user_id: int,
    text: str,
    quick_call: Callable[[str], str | Awaitable[str]],
):
    """Background: extract personal facts from `text` and persist them.
    Silent on failure — never blocks or bubbles into the user reply."""
    try:
        facts = await extract_facts_via_ai(text, quick_call)
        if not facts:
            return
        added = add_facts(repository, user_id, facts)
        if added:
            await repository.save()
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).debug("fact memory bg failed: %s", e)
