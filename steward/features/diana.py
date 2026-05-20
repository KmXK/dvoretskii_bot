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
    DIANA_PROMPT,
    Model,
    OpenRouterModel,
    make_openrouter_query,
    make_openrouter_stream,
    make_text_query,
)
from steward.helpers.ai_context import (
    execute_ai_request_streaming,
    register_ai_handler,
)
from steward.helpers.tg_streaming import stream_reply
from steward.session.step import Step


_STOP_CB = "diana:stop"
_GROK = OpenRouterModel.GROK_4_FAST


def _diana_call(uid, msgs):
    return make_openrouter_query(uid, _GROK, msgs, DIANA_PROMPT)


def _diana_stream(uid, msgs):
    return make_openrouter_stream(uid, _GROK, msgs, DIANA_PROMPT)


async def _quick_call(prompt: str) -> str:
    return await make_text_query(0, Model.FAST, [("user", prompt)], "")


class _DianaStep(Step):
    def __init__(self):
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            context.session_context["history"] = []
            keyboard = Keyboard.row(
                Button("Положить трубку", callback_data=_STOP_CB)
            ).to_markup()
            await context.update.message.reply_text(
                "Алло…",
                reply_markup=keyboard,
            )
            self.is_waiting = True
            return False

        history = context.session_context["history"]
        history.append(("user", context.message.text))
        stream = await _diana_stream(
            context.update.message.from_user.id,
            history,
        )
        collected: list[str] = []

        async def _tap():
            async for chunk in stream:
                collected.append(chunk)
                yield chunk

        await stream_reply(context.message, _tap())
        response = "".join(collected)
        history.append(("assistant", response))
        return False

    async def callback(self, context):
        return context.callback_query.data == _STOP_CB

    def stop(self):
        self.is_waiting = False


_PRIVATE_ONLY = "Диана работает только тет-а-тет. Напиши мне в личку."


def _is_private(ctx: FeatureContext) -> bool:
    return ctx.message is not None and ctx.message.chat.type == "private"


class DianaFeature(Feature):
    command = "diana"
    description = "Поболтать с Дианой по душам (18+, только в личке)"
    excluded_from_ai_router = True
    help_examples = [
        "/diana — начать разговор",
        "/diana привет — одна реплика",
    ]

    @on_init
    async def _register(self):
        register_ai_handler(
            "diana", _diana_call, _diana_stream, quick_call=_quick_call
        )

    @subcommand("", description="Начать разговор (только в личке)")
    async def start(self, ctx: FeatureContext):
        if not _is_private(ctx):
            await ctx.reply(_PRIVATE_ONLY)
            return
        await self.start_wizard("diana:chat", ctx)

    @subcommand("<text:rest>", description="Одна реплика (только в личке)", catchall=True)
    async def ask(self, ctx: FeatureContext, text: str):
        if not _is_private(ctx):
            await ctx.reply(_PRIVATE_ONLY)
            return
        await execute_ai_request_streaming(
            ctx, text, _diana_stream, "diana", quick_call=_quick_call
        )

    @wizard("diana:chat", step("chat", _DianaStep()))
    async def on_done(self, ctx: FeatureContext, **state):
        pass
