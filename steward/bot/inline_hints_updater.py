from typing import Callable, Optional, TypeGuard

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
        def check_not_null[T](x: Optional[T]) -> TypeGuard[T]:
            return x is not None

        command_texts = [
            *filter(check_not_null, (x.help() for x in self.handlers if filter_func(x)))
        ]

        def parse_help_msg(x: str):
            parts = x.split(" ")
            return (parts[0], " ".join(parts[1:]))

        commands = [parse_help_msg(x) for x in command_texts]

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
                await self._set_commands(
                    bot,
                    lambda _: True,
                    BotCommandScopeChatMember(chat_id, admin_id),
                )
