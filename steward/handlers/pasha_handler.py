from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import ChatBotContext
from steward.handlers.handler import Handler
from steward.helpers.ai import PASHA_PROMPT, make_yandex_ai_query
from steward.helpers.ai_context import execute_ai_request, register_ai_handler
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step

register_ai_handler(
    "pasha",
    lambda uid, msgs: make_yandex_ai_query(uid, msgs, PASHA_PROMPT),
)


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
            return False

        context.session_context[self.name].append(("user", context.message.text))

        response = await make_yandex_ai_query(
            context.update.message.from_user.id,
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


class PashaHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not context.message or not context.message.text:
            return False

        if context.message.text.startswith("/pasha") and len(context.message.text) > 7:
            text = context.message.text[7:]
            await execute_ai_request(
                context,
                text,
                lambda uid, msgs: make_yandex_ai_query(uid, msgs, PASHA_PROMPT),
                "pasha",
            )
            return True
        else:
            return False

    def help(self):
        return "/pasha <text> - задать вопрос Паше"
