from time import time

import telethon
from async_lru import alru_cache
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telethon import TelegramClient

from steward.bot.context import ChatBotContext
from steward.data.models.pasha_ai_message import PashaAiMessage
from steward.handlers.handler import Handler
from steward.helpers.ai import PASHA_PROMPT, AIModels, make_ai_query_ext
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step


class GptStep(Step):
    def __init__(self, name):
        self.name = name
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            context.session_context[self.name] = []
            await context.update.message.reply_text(
                "Слушаю...",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Закончить чат",
                                callback_data="pasha_handler|stop",
                            ),
                        ],
                    ]
                ),
            )
            self.is_waiting = True
            return False  # to stay on this handler in session

        context.session_context[self.name].append(("user", context.message.text))

        response = await make_ai_query_ext(
            context.update.message.from_user.id,
            AIModels.YANDEXGPT_5_PRO,
            context.session_context[self.name],
            PASHA_PROMPT,
        )

        if "Я не могу обсуждать эту тему." in response:
            await context.message.reply_text("Ой, иди нахуй")
            context.session_context[self.name].pop()
        else:
            await context.message.reply_text(response)
            context.session_context[self.name].append(("assistant", response))
        return False

    async def callback(self, context):
        if context.callback_query.data == "pasha_handler|stop":
            return True
        return False


class PashaSessionHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                GptStep("gpt"),
            ]
        )

    def try_activate_session(self, update, session_context):
        return update.message.text == "/pasha"

    async def on_session_finished(self, update, session_context):
        pass

    def help(self):
        return "/pasha - начать диалог с Пашей"


@alru_cache(1024)
async def get_message_by_id(tg_client: TelegramClient, chat_id, message_id):
    message = await tg_client.get_messages(chat_id, ids=message_id)
    assert message is None or isinstance(message, telethon.types.Message)
    return message


async def make_prompt_from_message(context: ChatBotContext, text: str):
    result = []

    message = await get_message_by_id(
        context.client,
        context.message.chat.id,
        context.message.id,
    )

    result.append(("user", text))

    while message:
        reply_to_msg_id = 0
        if message.reply_to and message.reply_to.reply_to_msg_id:  # type: ignore
            reply_to_msg_id = message.reply_to.reply_to_msg_id  # type: ignore
        elif (
            f"{context.message.chat.id}_{message.id}"
            in context.repository.db.pasha_ai_messages
        ):
            reply_to_msg_id = context.repository.db.pasha_ai_messages[
                f"{context.message.chat.id}_{message.id}"
            ].message_id

        if reply_to_msg_id == 0:
            break

        message = await get_message_by_id(
            context.client,
            context.message.chat.id,
            reply_to_msg_id,
        )

        if message and message.message:
            if message.from_id and message.from_id.user_id == context.bot.id:  # type: ignore
                result.append(("assistant", message.message))
            else:
                result.append(("user", message.message))

    return [*reversed(result)]


async def _execute_pasha_ai_request(context: ChatBotContext, text):
    response = await make_ai_query_ext(
        context.message.from_user.id,
        AIModels.YANDEXGPT_5_PRO,
        await make_prompt_from_message(context, text),
        PASHA_PROMPT,
    )
    message = await context.message.reply_markdown(response)

    context.repository.db.pasha_ai_messages[
        f"{context.message.chat.id}_{message.id}"
    ] = PashaAiMessage(time(), context.message.id)

    if len(context.repository.db.pasha_ai_messages) > 1000:
        oldest_message = min(
            context.repository.db.pasha_ai_messages,
            key=lambda k: context.repository.db.pasha_ai_messages[k].timestamp,
        )
        del context.repository.db.pasha_ai_messages[oldest_message]
    await context.repository.save()


class PashaHandler(Handler):
    async def chat(
        self,
        context: ChatBotContext,
    ):
        if not context.message or not context.message.text:
            return False

        if context.message.text.startswith("/pasha") and len(context.message.text) > 7:
            text = context.message.text[7:]
            await _execute_pasha_ai_request(context, text)
            return True
        else:
            return False

    def help(self):
        return "/pasha <text> - задать вопрос Паше"


class PashaRelatedMessageHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if (
            not context.message
            or not context.message.text
            or not context.message.reply_to_message
            or f"{context.message.chat.id}_{context.message.reply_to_message.id}"
            not in context.repository.db.pasha_ai_messages
        ):
            return False

        await _execute_pasha_ai_request(context, context.message.text)
        return True
