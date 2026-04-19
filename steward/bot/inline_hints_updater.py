from typing import Callable

from telegram import (
    BotCommandScope,
    BotCommandScopeChat,
    BotCommandScopeChatMember,
    BotCommandScopeDefault,
)
from telegram.error import TelegramError
from telegram.ext import ExtBot

from steward.data.repository import Repository
from steward.handlers.handler import Handler

_DESCRIPTION_LIMIT = 256


def _command_entry(handler: Handler) -> tuple[str, str] | None:
    """Return (command_name, description) for set_my_commands, or None if the
    handler should not appear in the Telegram command menu."""
    command = getattr(handler, "command", None)
    description = getattr(handler, "description", "") or ""

    if not command:
        # Fallback for legacy handlers that don't expose `command`: parse the
        # single-line help() string ("/foo - description").
        help_text = handler.help()
        if not help_text:
            return None
        first_line = help_text.split("\n", 1)[0]
        parts = first_line.split(" ", 1)
        name = parts[0]
        if not name.startswith("/"):
            return None
        description = parts[1] if len(parts) > 1 else ""
    else:
        name = f"/{command}"

    description = description.replace("\n", " ").strip()
    if len(description) > _DESCRIPTION_LIMIT:
        description = description[: _DESCRIPTION_LIMIT - 1].rstrip() + "…"
    if not description:
        description = name
    return name, description


class InlineHintsUpdater:
    def __init__(
        self,
        repository: Repository,
        handlers: list[Handler],
    ):
        self.repository = repository
        self.handlers = handlers

        self.chat_ids: set[int] = set()

    async def start(self, bot: ExtBot[None]):
        await self._update_admin_hints(bot)

        # for admins
        self.repository.subscribe_on_save(lambda: self._update_admin_hints(bot))
        for admin_id in self.repository.db.admin_ids:
            try:
                await self._set_commands(
                    bot,
                    lambda x: True,
                    BotCommandScopeChat(admin_id),
                )
            except TelegramError:
                pass  # chat can be deleted

        # for all users
        await self._set_commands(
            bot,
            lambda x: not x.only_for_admin,
            BotCommandScopeDefault(),
        )

    async def _set_commands(
        self,
        bot: ExtBot[None],
        filter_func: Callable[[Handler], bool],
        scope: BotCommandScope,
    ) -> bool:
        commands: list[tuple[str, str]] = []
        for handler in self.handlers:
            if not filter_func(handler):
                continue
            entry = _command_entry(handler)
            if entry is not None:
                commands.append(entry)
        return await bot.set_my_commands(commands, scope)

    async def _update_admin_hints(
        self,
        bot: ExtBot[None],
    ):
        if len(self.chat_ids) == len(self.repository.db.chats):
            return

        new_set = set((x.id for x in self.repository.db.chats if x.id < 0))
        diff = new_set - self.chat_ids

        self.chat_ids.update(new_set)

        # TODO: Clear commands for user on admin delete
        for chat_id in diff:
            for admin_id in self.repository.db.admin_ids:
                try:
                    await self._set_commands(
                        bot,
                        lambda _: True,
                        BotCommandScopeChatMember(chat_id, admin_id),
                    )
                except TelegramError:
                    pass  # chat can be deleted
