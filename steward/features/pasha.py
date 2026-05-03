from steward.framework import (
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    on_init,
    step,
    subcommand,
    wizard,
)
from steward.helpers.ai import (
    Model,
    PASHA_PROMPT,
    make_text_query,
    make_yandex_ai_query,
    make_yandex_ai_stream,
)
from steward.helpers.ai_context import (
    execute_ai_request_streaming,
    register_ai_handler,
)
from steward.helpers.tg_streaming import stream_reply
from steward.session.step import Step


_STOP_CB = "pasha:stop"


def _pasha_call(uid, msgs):
    return make_yandex_ai_query(uid, msgs, PASHA_PROMPT)


def _pasha_stream(uid, msgs):
    return make_yandex_ai_stream(uid, msgs, PASHA_PROMPT)


async def _quick_call(prompt: str) -> str:
    return await make_text_query(0, Model.FAST, [("user", prompt)], "")


class _GptStep(Step):
    def __init__(self):
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            context.session_context["history"] = []
            keyboard = Keyboard.row(
                Button("Закончить чат", callback_data=_STOP_CB)
            ).to_markup()
            await context.update.message.reply_text(
                "Слушаю...",
                reply_markup=keyboard,
            )
            self.is_waiting = True
            return False

        history = context.session_context["history"]
        history.append(("user", context.message.text))
        stream = await _pasha_stream(
            context.update.message.from_user.id,
            history,
        )
        collected: list[str] = []

        async def _tap():
            async for chunk in stream:
                collected.append(chunk)
                yield chunk

        bot_message = await stream_reply(context.message, _tap())
        response = "".join(collected)
        if "Я не могу обсуждать эту тему." in response:
            try:
                await bot_message.edit_text("Ой, иди нахуй")
            except Exception:
                pass
            history.pop()
        else:
            history.append(("assistant", response))
        return False

    async def callback(self, context):
        return context.callback_query.data == _STOP_CB

    def stop(self):
        self.is_waiting = False


class PashaFeature(Feature):
    command = "pasha"
    description = "Диалог с Пашей"
    excluded_from_ai_router = True

    @on_init
    async def _register(self):
        register_ai_handler("pasha", _pasha_call, _pasha_stream, quick_call=_quick_call)

    @subcommand("", description="Начать диалог")
    async def start(self, ctx: FeatureContext):
        await self.start_wizard("pasha:chat", ctx)

    @subcommand("<text:rest>", description="Одноразовый вопрос", catchall=True)
    async def ask(self, ctx: FeatureContext, text: str):
        await execute_ai_request_streaming(
            ctx, text, _pasha_stream, "pasha", quick_call=_quick_call
        )

    @wizard("pasha:chat", step("gpt", _GptStep()))
    async def on_done(self, ctx: FeatureContext, **state):
        pass
