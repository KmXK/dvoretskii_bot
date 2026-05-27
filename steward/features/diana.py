from time import time

from pyrate_limiter import BucketFullException

from steward.data.models.ai_message import AiMessage
from steward.framework import (
    Feature,
    FeatureContext,
    collection,
    on_init,
    on_message,
    subcommand,
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
from steward.helpers.limiter import Duration, check_limit


_GROK = OpenRouterModel.GROK_4_FAST
_GREETING = "Алло… слушаю тебя."
_DENIED = "Диана работает только тет-а-тет или в чате, где админ её разрешил."
_TOO_FAST = "Тише, тише. Дай мне отдышаться."
_TRIGGERS = ("грязная диана", "диана")
_RATE_LIMIT = 5
_RATE_WINDOW = 20 * Duration.SECOND


def _diana_call(uid, msgs):
    return make_openrouter_query(uid, _GROK, msgs, DIANA_PROMPT)


def _diana_stream(uid, msgs):
    return make_openrouter_stream(uid, _GROK, msgs, DIANA_PROMPT)


async def _quick_call(prompt: str) -> str:
    return await make_text_query(0, Model.FAST, [("user", prompt)], "")


_SEPARATORS = " ,:.!?\n\t—-"


def _strip_trigger(text: str) -> str | None:
    stripped = text.lstrip()
    low = stripped.lower()
    for trigger in _TRIGGERS:
        if not low.startswith(trigger):
            continue
        rest = stripped[len(trigger):]
        if rest and rest[0] not in _SEPARATORS:
            continue
        return rest.strip(_SEPARATORS)
    return None


class DianaFeature(Feature):
    command = "diana"
    description = "Поболтать с Дианой по душам (18+)"
    excluded_from_ai_router = True
    help_examples = [
        "/diana — начать разговор",
        "/diana привет — одна реплика",
        "диана, что думаешь? — обращение прямо в чате",
    ]

    allowed_chats = collection("diana_allowed_chats")

    @on_init
    async def _register(self):
        register_ai_handler(
            "diana", _diana_call, _diana_stream, quick_call=_quick_call
        )

    def _is_allowed(self, ctx: FeatureContext) -> bool:
        msg = ctx.message
        if msg is not None and msg.chat.type == "private":
            return True
        return ctx.chat_id in self.allowed_chats

    def _within_rate(self, user_id: int) -> bool:
        try:
            check_limit(
                "diana_user", _RATE_LIMIT, _RATE_WINDOW, name=str(user_id)
            )
            return True
        except BucketFullException:
            return False

    @subcommand(
        "allow",
        description="Открыть/закрыть Диану для всех в этом чате",
        admin=True,
    )
    async def allow(self, ctx: FeatureContext):
        if ctx.message is not None and ctx.message.chat.type == "private":
            await ctx.reply("В личке Диана и так всегда с тобой.")
            return
        if ctx.chat_id in self.allowed_chats:
            self.allowed_chats.remove(ctx.chat_id)
            await self.allowed_chats.save()
            await ctx.reply("Диана больше не работает в этом чате.")
            return
        self.allowed_chats.add(ctx.chat_id)
        await self.allowed_chats.save()
        await ctx.reply("Диана теперь доступна всем в этом чате.")

    @subcommand("", description="Начать разговор")
    async def start(self, ctx: FeatureContext):
        if not self._is_allowed(ctx):
            await ctx.reply(_DENIED)
            return
        if not self._within_rate(ctx.user_id):
            await ctx.reply(_TOO_FAST)
            return
        await self._send_greeting(ctx)

    @subcommand("<text:rest>", description="Одна реплика", catchall=True)
    async def ask(self, ctx: FeatureContext, text: str):
        if not self._is_allowed(ctx):
            await ctx.reply(_DENIED)
            return
        if not self._within_rate(ctx.user_id):
            await ctx.reply(_TOO_FAST)
            return
        await execute_ai_request_streaming(
            ctx, text, _diana_stream, "diana", quick_call=_quick_call
        )

    @on_message
    async def on_trigger(self, ctx: FeatureContext) -> bool:
        msg = ctx.message
        if msg is None or not msg.text or msg.text.startswith("/"):
            return False
        request = _strip_trigger(msg.text)
        if request is None:
            return False
        if not self._is_allowed(ctx):
            return False
        if not self._within_rate(ctx.user_id):
            await ctx.reply(_TOO_FAST)
            return True
        if not request:
            await self._send_greeting(ctx)
            return True
        await execute_ai_request_streaming(
            ctx, request, _diana_stream, "diana", quick_call=_quick_call
        )
        return True

    async def _send_greeting(self, ctx: FeatureContext) -> None:
        sent = await ctx.reply(_GREETING)
        if sent is None or ctx.message is None:
            return
        ctx.repository.db.ai_messages[f"{ctx.chat_id}_{sent.id}"] = AiMessage(
            time(), ctx.message.id, "diana"
        )
        await ctx.repository.save()
