from time import time

from steward.data.models.ai_message import AiMessage
from steward.framework import Feature, FeatureContext, on_init, subcommand
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


_GROK = OpenRouterModel.GROK_4_FAST
_PRIVATE_ONLY = "Диана работает только тет-а-тет. Напиши мне в личку."
_GREETING = "Алло… слушаю тебя."


def _diana_call(uid, msgs):
    return make_openrouter_query(uid, _GROK, msgs, DIANA_PROMPT)


def _diana_stream(uid, msgs):
    return make_openrouter_stream(uid, _GROK, msgs, DIANA_PROMPT)


async def _quick_call(prompt: str) -> str:
    return await make_text_query(0, Model.FAST, [("user", prompt)], "")


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
        msg = await ctx.reply(_GREETING)
        if msg is None or ctx.message is None:
            return
        ctx.repository.db.ai_messages[f"{ctx.chat_id}_{msg.id}"] = AiMessage(
            time(), ctx.message.id, "diana"
        )
        await ctx.repository.save()

    @subcommand("<text:rest>", description="Одна реплика (только в личке)", catchall=True)
    async def ask(self, ctx: FeatureContext, text: str):
        if not _is_private(ctx):
            await ctx.reply(_PRIVATE_ONLY)
            return
        await execute_ai_request_streaming(
            ctx, text, _diana_stream, "diana", quick_call=_quick_call
        )
