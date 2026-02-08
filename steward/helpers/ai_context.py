from inspect import isawaitable
from time import time
from typing import Awaitable, Callable

import telethon
from async_lru import alru_cache
from telethon import TelegramClient

from steward.bot.context import ChatBotContext
from steward.data.models.ai_message import AiMessage

type AiCallable = Callable[[int, list[tuple[str, str]]], str | Awaitable[str]]

_ai_handlers: dict[str, AiCallable] = {}


def register_ai_handler(name: str, call: AiCallable):
    _ai_handlers[name] = call


def get_ai_handler(name: str) -> AiCallable | None:
    return _ai_handlers.get(name)


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
