"""Base for AI-persona features.

Personas answer in three ways:
  - /<command> [text]              explicit slash invocation
  - "<alias>, ..." in chat         trigger-word invocation (aliases_in_chat)
  - reply to a bot message         AiRelatedFeature routes back via persona_name

Subclasses set class-level config and override `_call` / `_stream` (and
optionally `_post_process`). Shared concerns live here: registration of the
AI handler, rate limiting, slash subcommands, chat trigger, greeting, and the
optional per-chat allowlist with its admin-only `allow` subcommand.
"""

from time import time
from typing import Any, AsyncIterator, Awaitable, Callable, ClassVar

from pyrate_limiter import BucketFullException
from telegram import Message

from steward.data.models.ai_message import AiMessage
from steward.framework import (
    Feature,
    FeatureContext,
    on_init,
    on_message,
    subcommand,
)
from steward.framework.collection import SetCollection, _build_collection
from steward.helpers.ai import Model, make_text_query
from steward.helpers.ai_context import (
    execute_ai_request_streaming,
    register_ai_handler,
)
from steward.helpers.limiter import Duration, check_limit


_TRIGGER_SEPARATORS = " ,:.!?\n\t—-"


def strip_trigger(text: str, triggers: tuple[str, ...]) -> str | None:
    """If `text` begins with any of `triggers` followed by a separator, return
    the remaining text (separators trimmed). Otherwise None.

    Triggers are matched case-insensitively and longest-first wins via the
    caller's ordering.
    """
    stripped = text.lstrip()
    low = stripped.lower()
    for trigger in triggers:
        if not low.startswith(trigger):
            continue
        rest = stripped[len(trigger):]
        if rest and rest[0] not in _TRIGGER_SEPARATORS:
            continue
        return rest.strip(_TRIGGER_SEPARATORS)
    return None


async def _default_quick_call(prompt: str) -> str:
    return await make_text_query(0, Model.FAST, [("user", prompt)], "")


class AiPersonaFeature(Feature):
    persona_name: ClassVar[str] = ""
    aliases_in_chat: ClassVar[tuple[str, ...]] = ()
    greeting: ClassVar[str | None] = None
    allowed_chats_key: ClassVar[str | None] = None  # None → не chat-gated
    rate_limit: ClassVar[int] = 5
    rate_window: ClassVar[int] = 20 * Duration.SECOND
    denied_message: ClassVar[str] = "Я работаю только тет-а-тет или в разрешённом чате."
    rate_limited_message: ClassVar[str] = "Тише, тише. Дай мне отдышаться."
    private_allow_message: ClassVar[str] = "В личке я и так всегда с тобой."
    allow_on_message: ClassVar[str] = "Теперь доступна всем в этом чате."
    allow_off_message: ClassVar[str] = "Больше не работаю в этом чате."

    excluded_from_ai_router = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # If a subclass is not chat-gated, hide the base's `allow` subcommand
        # so it doesn't waste a slot or confuse help output.
        if cls.allowed_chats_key is None:
            cls._subcommands = [
                s for s in cls._subcommands
                if getattr(s.func, "__name__", "") != "_persona_allow"
            ]

    async def _call(self, user_id: int, messages: list[tuple[str, str]]) -> str:
        raise NotImplementedError

    async def _stream(
        self, user_id: int, messages: list[tuple[str, str]]
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def _quick_call(self, prompt: str) -> str:
        return await _default_quick_call(prompt)

    async def _post_process(
        self, bot_message: Message, full_text: str
    ) -> None:
        """Hook after the stream finishes. Default: no-op.
        Override to inspect or rewrite the final message (e.g. content-filter
        substitution)."""

    @on_init
    async def _persona_init(self):
        assert self.persona_name, f"{type(self).__name__}: persona_name not set"
        register_ai_handler(
            self.persona_name,
            self._call,
            self._stream,
            quick_call=self._quick_call,
        )

    def _allowed_chats(self) -> SetCollection[int] | None:
        if self.allowed_chats_key is None:
            return None
        return _build_collection(self.repository, self.allowed_chats_key, "id")

    def _is_allowed(self, ctx: FeatureContext) -> bool:
        chats = self._allowed_chats()
        if chats is None:
            return True
        msg = ctx.message
        if msg is not None and msg.chat.type == "private":
            return True
        return ctx.chat_id in chats

    def _within_rate(self, user_id: int) -> bool:
        try:
            check_limit(
                f"persona_{self.persona_name}",
                self.rate_limit,
                self.rate_window,
                name=str(user_id),
            )
            return True
        except BucketFullException:
            return False

    async def _gate(self, ctx: FeatureContext) -> bool:
        if not self._is_allowed(ctx):
            await ctx.reply(self.denied_message)
            return False
        if not self._within_rate(ctx.user_id):
            await ctx.reply(self.rate_limited_message)
            return False
        return True

    async def _execute(self, ctx: FeatureContext, text: str) -> None:
        post_process = self._post_process_callable()
        await execute_ai_request_streaming(
            ctx,
            text,
            self._stream,
            self.persona_name,
            quick_call=self._quick_call,
            post_process=post_process,
        )

    def _post_process_callable(
        self,
    ) -> Callable[[Message, str], Awaitable[None] | None] | None:
        # Skip the tap overhead when the subclass hasn't overridden the hook.
        if type(self)._post_process is AiPersonaFeature._post_process:
            return None
        return self._post_process

    async def _send_greeting(self, ctx: FeatureContext) -> None:
        if self.greeting is None:
            return
        sent = await ctx.reply(self.greeting)
        if sent is None or ctx.message is None:
            return
        ctx.repository.db.ai_messages[f"{ctx.chat_id}_{sent.id}"] = AiMessage(
            time(), ctx.message.id, self.persona_name
        )
        await ctx.repository.save()

    @subcommand("", description="Начать разговор")
    async def _persona_start(self, ctx: FeatureContext):
        if not await self._gate(ctx):
            return
        await self._send_greeting(ctx)

    @subcommand("<text:rest>", description="Одна реплика", catchall=True)
    async def _persona_ask(self, ctx: FeatureContext, text: str):
        if not await self._gate(ctx):
            return
        await self._execute(ctx, text)

    @subcommand(
        "allow",
        description="Открыть/закрыть для всех в этом чате",
        admin=True,
    )
    async def _persona_allow(self, ctx: FeatureContext):
        chats = self._allowed_chats()
        if chats is None:
            return False
        if ctx.message is not None and ctx.message.chat.type == "private":
            await ctx.reply(self.private_allow_message)
            return
        if ctx.chat_id in chats:
            chats.remove(ctx.chat_id)
            await chats.save()
            await ctx.reply(self.allow_off_message)
            return
        chats.add(ctx.chat_id)
        await chats.save()
        await ctx.reply(self.allow_on_message)

    @on_message
    async def _persona_on_trigger(self, ctx: FeatureContext) -> bool:
        if not self.aliases_in_chat:
            return False
        msg = ctx.message
        if msg is None or not msg.text or msg.text.startswith("/"):
            return False
        request = strip_trigger(msg.text, self.aliases_in_chat)
        if request is None:
            return False
        if not self._is_allowed(ctx):
            return False
        if not self._within_rate(ctx.user_id):
            await ctx.reply(self.rate_limited_message)
            return True
        if not request:
            if self.greeting is None:
                return False
            await self._send_greeting(ctx)
            return True
        await self._execute(ctx, request)
        return True
