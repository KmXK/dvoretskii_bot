import logging

from telegram import MessageEntity

from steward.data.models.command_alias import CommandAlias
from steward.framework import (
    Feature,
    FeatureContext,
    collection,
    on_message,
    subcommand,
)

logger = logging.getLogger(__name__)

MAX_ALIASES_PER_CHAT = 100
ARGS_PLACEHOLDER = "{args}"


class AliasFeature(Feature):
    """Per-chat user-defined command shortcuts.

    Управляется командой `/alias` (любым участником чата). Раскрытие триггеров
    работает через `@on_message`: когда первое слово сообщения совпадает с
    триггером чата, текст сообщения переписывается в раскрытие и пропускается
    через обычный конвейер хендлеров — будто пользователь набрал команду сам.

    Фича стоит первой в EARLY-бакете, поэтому раскрытый текст видят и мониторы,
    и командные фичи (со всеми проверками прав/capability).
    """

    command = "alias"
    description = "Свои команды-сокращения для чата"

    aliases_col = collection("command_aliases")

    # ------------------------------------------------------------------ #
    # Management commands
    # ------------------------------------------------------------------ #

    @subcommand("", description="Список алиасов чата")
    async def list_(self, ctx: FeatureContext):
        items = self._chat_aliases(ctx.chat_id)
        if not items:
            await ctx.reply(
                "В этом чате нет алиасов.\n\n"
                "Добавить: `/alias add #done /curse done 1 100`\n"
                "Потом напиши `#done` — выполнится `/curse done 1 100`.\n\n"
                "Хвост сообщения дописывается к команде, либо подставляется "
                "в `{args}`. Например `/alias add #fine /curse done {args}`, "
                "затем `#fine 1 100`."
            )
            return
        lines = ["*Алиасы этого чата:*", ""]
        for a in sorted(items, key=lambda x: x.trigger.lower()):
            lines.append(f"`{a.trigger}` → `{a.expansion}`")
        await ctx.reply("\n".join(lines))

    @subcommand("add <trigger:str> <expansion:rest>", description="Добавить/обновить алиас")
    async def add(self, ctx: FeatureContext, trigger: str, expansion: str):
        trigger = trigger.strip()
        expansion = expansion.strip()
        if trigger.lstrip("/").split("@")[0].lower() == self.command:
            await ctx.reply("Нельзя сделать алиас на `/alias`.")
            return

        existing = self._find(ctx.chat_id, trigger)
        if existing is None and len(self._chat_aliases(ctx.chat_id)) >= MAX_ALIASES_PER_CHAT:
            await ctx.reply(f"Слишком много алиасов (лимит {MAX_ALIASES_PER_CHAT}).")
            return

        if existing is not None:
            self.aliases_col.remove(existing)
        self.aliases_col.add(
            CommandAlias(
                chat_id=ctx.chat_id,
                trigger=trigger,
                expansion=expansion,
                created_by=ctx.user_id,
            )
        )
        await self.aliases_col.save()

        verb = "обновлён" if existing is not None else "добавлен"
        hint = ""
        if not expansion.startswith("/"):
            hint = "\n⚠️ Раскрытие не начинается с `/` — оно будет отправлено как обычный текст."
        await ctx.reply(f"Алиас `{trigger}` → `{expansion}` {verb}.{hint}")

    @subcommand("remove <trigger:str>", description="Удалить алиас")
    async def remove(self, ctx: FeatureContext, trigger: str):
        existing = self._find(ctx.chat_id, trigger.strip())
        if existing is None:
            await ctx.reply(f"Алиаса `{trigger}` в этом чате нет.")
            return
        self.aliases_col.remove(existing)
        await self.aliases_col.save()
        await ctx.reply(f"Алиас `{trigger}` удалён.")

    @subcommand("rm <trigger:str>", description="Удалить алиас")
    async def remove_alt(self, ctx: FeatureContext, trigger: str):
        await self.remove(ctx, trigger)

    # ------------------------------------------------------------------ #
    # Trigger expansion
    # ------------------------------------------------------------------ #

    @on_message
    async def expand(self, ctx: FeatureContext) -> bool:
        msg = ctx.message
        if msg is None or not msg.text:
            return False
        text = msg.text
        # Слэш-команды не трогаем: они уже идут штатным путём, плюс это
        # защищает от перекрытия реальных команд и от зацикливания.
        if text.startswith("/"):
            return False

        parts = text.split(None, 1)
        if not parts:
            return False
        first = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""

        alias = self._find(ctx.chat_id, first)
        if alias is None:
            return False

        if ARGS_PLACEHOLDER in alias.expansion:
            final = alias.expansion.replace(ARGS_PLACEHOLDER, rest)
        else:
            final = alias.expansion + (f" {rest}" if rest else "")
        final = final.strip()
        if not final:
            return False

        logger.info(
            "Alias expanded in chat %s: %r -> %r", ctx.chat_id, first, final
        )
        self._patch_message(msg, final)
        # Возвращаем False — раскрытый текст должен пройти весь конвейер
        # (мониторы + командные фичи), как если бы его набрал пользователь.
        return False

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _chat_aliases(self, chat_id: int) -> list[CommandAlias]:
        return self.aliases_col.filter(chat_id=chat_id)

    def _find(self, chat_id: int, trigger: str) -> CommandAlias | None:
        t = trigger.lower()
        return self.aliases_col.find_one(
            lambda a: a.chat_id == chat_id and a.trigger.lower() == t
        )

    @staticmethod
    def _patch_message(message, command: str) -> None:
        """Rewrite the live message so downstream handlers see `command`.

        Mirrors AiRouterHandler._patch_message. Adds a BOT_COMMAND entity only
        when the expansion is a slash-command; plain-text expansions flow as a
        normal message.
        """
        was_frozen = getattr(message, "_frozen", False)
        if was_frozen:
            object.__setattr__(message, "_frozen", False)
        message.text = command
        if command.startswith("/"):
            cmd_part = command.split()[0]
            message.entities = (
                MessageEntity(
                    type=MessageEntity.BOT_COMMAND,
                    offset=0,
                    length=len(cmd_part),
                ),
            )
        else:
            message.entities = ()
        if was_frozen:
            object.__setattr__(message, "_frozen", True)
