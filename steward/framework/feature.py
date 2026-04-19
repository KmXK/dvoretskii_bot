import inspect
import logging
from typing import Any, Awaitable, Callable

from telegram import Update
from telegram.ext import ExtBot
from telethon import TelegramClient

from steward.bot.context import (
    CallbackBotContext,
    ChatBotContext,
    ReactionBotContext,
)
from steward.data.repository import Repository
from steward.framework.callback_route import (
    CallbackFactory,
    CallbackRoute,
)
from steward.framework.keyboard import Button, Keyboard
from steward.framework.pagination import (
    _PaginatorSpec,
    _build_page_keyboard,
    _split_pagination_data,
    call_paginator,
)
from steward.framework.subcommand import Subcommand, sort_subcommands
from steward.framework.types import (
    FeatureContext,
    from_callback_context,
    from_chat_context,
    from_reaction_context,
)
from steward.framework.wizard import (
    CustomStepSpec,
    FeatureWizardSession,
    WizardSpec,
    _AdhocSession,
)
from steward.handlers.handler import Handler
from steward.helpers.command_validation import (
    ValidationArgumentsError,
    validate_command_msg,
)
from steward.metrics.base import ContextMetrics
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.session_registry import activate_session
from steward.session.step import Step

logger = logging.getLogger(__name__)


class Feature(Handler):
    command: str | None = None
    aliases: tuple[str, ...] = ()
    description: str = ""
    only_admin: bool = False
    excluded_from_ai_router: bool = False
    help_examples: list[str] = []
    custom_help: str | None = None
    custom_prompt: str | None = None

    _subcommands: list[Subcommand]
    _callbacks: list[CallbackRoute]
    _wizards: dict[str, WizardSpec]
    _paginators: dict[str, _PaginatorSpec]
    _custom_steps: dict[str, type]
    _on_init_hooks: list[Callable]
    _on_message_handlers: list[Callable]
    _on_reaction_handlers: list[Callable]
    _wizard_sessions: dict[str, FeatureWizardSession]
    _adhoc_sessions: list[_AdhocSession]

    client: TelegramClient = None  # type: ignore

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._collect_declarations()
        cls.only_for_admin = cls.only_admin

    @classmethod
    def _collect_declarations(cls) -> None:
        subcommands: list[Subcommand] = []
        callbacks: list[CallbackRoute] = []
        wizards: dict[str, WizardSpec] = {}
        paginators: dict[str, _PaginatorSpec] = {}
        custom_steps: dict[str, type] = {}
        init_hooks: list[Callable] = []
        message_handlers: list[Callable] = []
        reaction_handlers: list[Callable] = []
        seen: set[str] = set()

        for klass in reversed(cls.__mro__):
            if klass is object:
                continue
            for attr_name in klass.__dict__:
                if attr_name in seen:
                    continue
                attr = getattr(cls, attr_name, None)
                if attr is None:
                    continue
                seen.add(attr_name)
                for sub in getattr(attr, "_feature_subcommands", []) or []:
                    subcommands.append(sub)
                for cb in getattr(attr, "_feature_callbacks", []) or []:
                    callbacks.append(cb)
                wiz_spec = getattr(attr, "_feature_wizard", None)
                if wiz_spec is not None and wiz_spec.name not in wizards:
                    wizards[wiz_spec.name] = wiz_spec
                pag_spec = getattr(attr, "_feature_paginator", None)
                if pag_spec is not None and pag_spec.name not in paginators:
                    paginators[pag_spec.name] = pag_spec
                cs_spec: CustomStepSpec | None = getattr(attr, "_feature_custom_step", None)
                if cs_spec is not None:
                    custom_steps[cs_spec.name] = cs_spec.step_cls
                if getattr(attr, "_feature_on_init", False):
                    init_hooks.append(attr)
                if getattr(attr, "_feature_on_message", False):
                    message_handlers.append(attr)
                if getattr(attr, "_feature_on_reaction", False):
                    reaction_handlers.append(attr)

        cls._subcommands = sort_subcommands(subcommands)
        cls._callbacks = callbacks
        cls._wizards = wizards
        cls._paginators = paginators
        cls._custom_steps = custom_steps
        cls._on_init_hooks = init_hooks
        cls._on_message_handlers = message_handlers
        cls._on_reaction_handlers = reaction_handlers

    def __init__(self):
        self._wizard_sessions = {}
        for name, spec in self._wizards.items():
            self._wizard_sessions[name] = FeatureWizardSession(self, spec)
        self._adhoc_sessions = []

    def cb(self, name: str) -> CallbackFactory:
        for route in self._callbacks:
            if route.schema.name == name:
                return CallbackFactory(route.schema)
        raise KeyError(f"No callback route registered: {name!r}")

    def get_command(self) -> str | None:
        return self.command

    def get_command_with_aliases(self) -> list[str]:
        if self.command is None:
            return []
        return [self.command, *self.aliases]

    async def init(self) -> None:
        for hook in self._on_init_hooks:
            result = hook(self)
            if inspect.isawaitable(result):
                await result

    async def chat(self, ctx: ChatBotContext) -> bool:  # type: ignore[override]
        if self.command is not None:
            commands = self.get_command_with_aliases()
            validation = validate_command_msg(ctx.update, commands)
            if validation:
                args = self._extract_args(ctx, commands)
                feature_ctx = from_chat_context(ctx)
                handled = await self._dispatch_subcommand(feature_ctx, args)
                if handled:
                    return True

        for handler in self._on_message_handlers:
            feature_ctx = from_chat_context(ctx)
            try:
                result = await handler(self, feature_ctx)
            except ValidationArgumentsError:
                raise
            if result is True:
                return True
        return False

    async def callback(self, ctx: CallbackBotContext) -> bool:  # type: ignore[override]
        data = ctx.callback_query.data if ctx.callback_query else None
        if not data:
            return False

        if self._paginators:
            parsed = _split_pagination_data(self._pagination_prefix, data)
            if parsed is not None:
                name, metadata, page = parsed
                spec = self._paginators.get(name)
                if spec is not None:
                    feature_ctx = from_callback_context(ctx)
                    await self._render_paginator(feature_ctx, spec, metadata, page, edit=True)
                    return True

        for route in self._callbacks:
            parsed_cb = route.schema.parse(data)
            if parsed_cb is None:
                continue
            feature_ctx = from_callback_context(ctx)
            if route.only_initiator and route.initiator_field in parsed_cb:
                expected = parsed_cb[route.initiator_field]
                if feature_ctx.user_id != expected:
                    return False
            try:
                result = await route.func(self, feature_ctx, **parsed_cb)
            except TypeError:
                logger.exception("Callback handler signature mismatch: %s", route.schema.name)
                raise
            if result is False:
                return False
            return True

        return False

    async def reaction(self, ctx: ReactionBotContext) -> bool:  # type: ignore[override]
        if not self._on_reaction_handlers:
            return False
        feature_ctx = from_reaction_context(ctx)
        for handler in self._on_reaction_handlers:
            result = await handler(self, feature_ctx)
            if result is True:
                return True
        return False

    def _extract_args(self, ctx: ChatBotContext, commands: list[str]) -> str:
        text = (ctx.message.text or "").strip()
        if not text:
            return ""
        for cmd in commands:
            for prefix in (f"/{cmd}@", f"/{cmd}"):
                if text.lower().startswith(prefix.lower()):
                    rest = text[len(prefix) :]
                    if prefix.endswith("@"):
                        space_idx = rest.find(" ")
                        if space_idx == -1:
                            return ""
                        return rest[space_idx + 1 :].strip()
                    if not rest or rest[0] in (" ", "\n", "\t"):
                        return rest.strip()
        return ""

    async def _dispatch_subcommand(self, ctx: FeatureContext, args: str) -> bool:
        last_error: ValidationArgumentsError | None = None
        for sub in self._subcommands:
            ok, parsed = sub.matches(args)
            if not ok:
                continue
            if sub.admin and not ctx.repository.is_admin(ctx.user_id):
                await ctx.reply("Недостаточно прав.")
                return True
            try:
                result = await sub.func(self, ctx, **parsed)
            except ValidationArgumentsError as e:
                last_error = e
                continue
            if result is False:
                continue
            if sub.then_wizard is not None and result is None:
                await self.start_wizard(sub.then_wizard, ctx)
            return True

        if last_error is not None:
            raise last_error
        if self._subcommands:
            raise ValidationArgumentsError()
        return False

    def help(self) -> str | None:  # type: ignore[override]
        if self.custom_help is not None:
            return self.custom_help
        if self.command is None:
            return None
        spec_lines = []
        for sub in self._subcommands:
            if not sub.description:
                continue
            usage = self._format_usage(sub)
            spec_lines.append(f"  {usage} — {sub.description}")
        head = f"/{self.command}"
        if self.description:
            head = f"{head} — {self.description}"
        if not spec_lines:
            return head
        return "\n".join([head, *spec_lines])

    def help_compact(self) -> str | None:
        """Single-line summary: `/cmd — description (sub1, sub2, ...)`."""
        if self.command is None:
            return None
        head = f"/{self.command}"
        if self.description:
            head = f"{head} — {self.description}"
        names = self._subcommand_literal_names()
        if names:
            head = f"{head} ({', '.join(names)})"
        return head

    def _subcommand_literal_names(self) -> list[str]:
        from steward.framework.subcommand import _Literal

        seen: set[str] = set()
        ordered: list[str] = []
        for sub in self._subcommands:
            if sub.spec is None or not sub.spec.tokens:
                continue
            first = sub.spec.tokens[0]
            if isinstance(first, _Literal) and first.value not in seen:
                seen.add(first.value)
                ordered.append(first.value)
        return ordered

    def prompt(self) -> str | None:  # type: ignore[override]
        if self.custom_prompt is not None:
            return self.custom_prompt
        if self.command is None or self.excluded_from_ai_router:
            return None
        lines = [f"▶ /{self.command}" + (f" — {self.description}" if self.description else "")]
        for sub in self._subcommands:
            if not sub.description:
                continue
            usage = self._format_usage(sub)
            lines.append(f"  {sub.description}: {usage}")
        if self.help_examples:
            lines.append("  Примеры:")
            for ex in self.help_examples:
                lines.append(f"  - {ex}")
        return "\n".join(lines)

    def _format_usage(self, sub: Subcommand) -> str:
        if sub.spec is None:
            return f"/{self.command} (regex)"
        from steward.framework.subcommand import _Literal, _Param

        parts: list[str] = [f"/{self.command}"]
        for tok in sub.spec.tokens:
            if isinstance(tok, _Literal):
                parts.append(tok.value)
            else:
                if tok.options:
                    parts.append("|".join(tok.options))
                else:
                    parts.append(f"<{tok.name}>")
        return " ".join(parts)

    @property
    def _pagination_prefix(self) -> str:
        return f"{self.command or type(self).__name__.lower()}:_pg"

    async def paginate(
        self,
        ctx: FeatureContext,
        name: str,
        *,
        metadata: str = "",
        page: int = 0,
    ) -> None:
        spec = self._paginators.get(name)
        if spec is None:
            raise KeyError(f"No paginator registered: {name!r} on {type(self).__name__}")
        await self._render_paginator(ctx, spec, metadata, page, edit=ctx.is_callback)

    def page_button(self, name: str, label: str, *, metadata: str = "", page: int = 0) -> Button:
        return Button(
            label,
            callback_data=f"{self._pagination_prefix}|{name}|{metadata}|{page}",
        )

    async def _render_paginator(
        self,
        ctx: FeatureContext,
        spec: _PaginatorSpec,
        metadata: str,
        page: int,
        edit: bool,
    ) -> None:
        items, render, extra = await call_paginator(spec, self, ctx, metadata)
        total = len(items)
        pages = max(1, (total + spec.per_page - 1) // spec.per_page)
        page = max(0, min(page, pages - 1))
        start = page * spec.per_page
        chunk = items[start : start + spec.per_page]
        body = render(chunk) if chunk else spec.empty_text
        text = f"{spec.header}\n\n{body}" if spec.header else body
        kb = _build_page_keyboard(
            self._pagination_prefix, spec.name, metadata, page, pages, extra
        )
        if edit:
            await ctx.edit(
                text,
                keyboard=kb,
                markdown=(spec.parse_mode == "markdown"),
                html=(spec.parse_mode and spec.parse_mode.lower() == "html"),
            )
        else:
            await ctx.reply(
                text,
                keyboard=kb,
                markdown=(spec.parse_mode == "markdown"),
                html=(spec.parse_mode and spec.parse_mode.lower() == "html"),
            )

    async def start_wizard(self, name: str, ctx: FeatureContext, **initial: Any) -> bool:
        if name not in self._wizard_sessions:
            raise KeyError(f"No wizard registered: {name!r}")
        session = self._wizard_sessions[name]
        session.stage_start(ctx.update, initial)
        await self._activate_session(session, ctx)
        return True

    async def start_session(
        self,
        steps: list[Step],
        ctx: FeatureContext,
        *,
        on_done: Callable[..., Awaitable[Any]] | None = None,
        on_stop: Callable[..., Awaitable[Any]] | None = None,
        **initial: Any,
    ) -> bool:
        session = _AdhocSession(self, steps, on_done=on_done, on_stop=on_stop)
        self._adhoc_sessions.append(session)
        session.stage_start(ctx.update, initial)
        await self._activate_session(session, ctx)
        return True

    async def _activate_session(
        self, session: SessionHandlerBase, ctx: FeatureContext
    ) -> None:
        session.repository = self.repository
        session.bot = self.bot
        activate_session(session, ctx.update)
        if ctx.callback_query is not None:
            cb_ctx = CallbackBotContext(
                repository=ctx.repository,
                bot=ctx.bot,
                client=ctx.client,
                update=ctx.update,
                tg_context=ctx.tg_context,
                metrics=ctx.metrics,
                callback_query=ctx.callback_query,
            )
            await session.callback(cb_ctx)
        elif ctx.message is not None:
            chat_ctx = ChatBotContext(
                repository=ctx.repository,
                bot=ctx.bot,
                client=ctx.client,
                update=ctx.update,
                tg_context=ctx.tg_context,
                metrics=ctx.metrics,
                message=ctx.message,
            )
            await session.chat(chat_ctx)

    def _make_wizard_context(self, update: Update) -> FeatureContext:
        message = update.message
        callback_query = update.callback_query
        return FeatureContext(
            update=update,
            tg_context=None,  # type: ignore
            repository=self.repository,
            bot=self.bot,
            client=self.client,
            metrics=ContextMetrics(None, {}),  # type: ignore
            message=message,
            callback_query=callback_query,
        )


def on_init(func):
    setattr(func, "_feature_on_init", True)
    return func


def on_message(func):
    setattr(func, "_feature_on_message", True)
    setattr(func, "_feature_marker", "on_message")
    return func


def on_reaction(func):
    setattr(func, "_feature_on_reaction", True)
    setattr(func, "_feature_marker", "on_reaction")
    return func
