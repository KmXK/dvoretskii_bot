from typing import TypeGuard

from steward.framework import Feature, FeatureContext, subcommand
from steward.handlers.handler import Handler


def _compact_line(handler: Handler) -> str | None:
    if hasattr(handler, "help_compact"):
        line = handler.help_compact()
        if line is not None:
            return line
    return _legacy_first_line(handler)


def _legacy_first_line(handler: Handler) -> str | None:
    msg = handler.help() if handler.help else None
    if not msg:
        return None
    return msg.split("\n", 1)[0]


def _build_overview(handlers: list[Handler], is_admin: bool) -> str:
    def keep(s: str | None) -> TypeGuard[str]:
        return s is not None and s != ""

    entries = [
        line
        for line in (
            _compact_line(h)
            for h in handlers
            if is_admin or not h.only_for_admin
        )
        if keep(line)
    ]
    entries.sort()
    if not entries:
        return "Список команд пуст"
    return "\n".join([
        "Список команд:",
        "",
        *entries,
        "",
        "Подробности по команде: /help <команда>",
    ])


def _find_handler(handlers: list[Handler], command: str) -> Handler | None:
    normalized = command.lstrip("/").split("@", 1)[0].lower()
    if not normalized:
        return None
    for handler in handlers:
        names = []
        if hasattr(handler, "get_command_with_aliases"):
            names = handler.get_command_with_aliases()
        elif getattr(handler, "command", None):
            names = [handler.command]
        for name in names:
            if name and name.lower() == normalized:
                return handler
    return None


class HelpFeature(Feature):
    command = "help"
    description = "Показать список команд"
    help_examples = [
        "«какие команды есть» → /help",
        "«помощь» → /help",
        "«подробнее про /remind» → /help remind",
    ]

    def __init__(self, handlers: list[Handler]):
        super().__init__()
        self._handlers = handlers

    @subcommand("", description="Список всех команд")
    async def overview(self, ctx: FeatureContext):
        is_admin = ctx.repository.is_admin(ctx.user_id)
        await ctx.reply(_build_overview(self._handlers, is_admin), markdown=False)

    @subcommand("<command:str>", description="Подробно про конкретную команду")
    async def details(self, ctx: FeatureContext, command: str):
        handler = _find_handler(self._handlers, command)
        if handler is None:
            await ctx.reply(f"Команда {command!r} не найдена")
            return
        if handler.only_for_admin and not ctx.repository.is_admin(ctx.user_id):
            await ctx.reply(f"Команда {command!r} не найдена")
            return
        text = handler.help() if handler.help else None
        if not text:
            await ctx.reply(f"У команды {command!r} нет описания")
            return
        await ctx.reply(text, markdown=False)
