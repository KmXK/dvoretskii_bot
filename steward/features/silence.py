import logging
from datetime import datetime, timezone

from steward.framework import (
    Feature,
    FeatureContext,
    collection,
    on_message,
    subcommand,
)
from steward.helpers.duration import format_timedelta, parse_duration

logger = logging.getLogger(__name__)


_OFF_TOKENS = {"off", "stop", "cancel", "0"}


class SilenceFeature(Feature):
    command = "silence"
    only_admin = True
    description = "Режим тишины"
    help_examples = [
        "«включи тишину на 30 минут» → /silence 30m",
        "«выключи режим тишины» → /silence off",
    ]

    silenced = collection("silenced_chats")

    @subcommand("", description="Выключить режим тишины")
    async def off_default(self, ctx: FeatureContext):
        await self._off(ctx)

    @subcommand("<arg:rest>", description="Включить (на время) или выключить", catchall=True)
    async def toggle(self, ctx: FeatureContext, arg: str):
        if arg.strip().lower() in _OFF_TOKENS:
            await self._off(ctx)
            return
        delta = parse_duration(arg.strip().lower())
        if delta is None:
            await ctx.reply(
                "Не получилось распознать время. Используй формат вида 10m, 2h30m, 45s."
            )
            return
        expires_at = datetime.now(timezone.utc) + delta
        self.silenced.set(ctx.chat_id, expires_at)
        await self.silenced.save()
        await ctx.reply(
            f"Режим тишины включен на {format_timedelta(delta)}. "
            "Все новые сообщения будут удаляться."
        )

    async def _off(self, ctx: FeatureContext):
        if self.silenced.pop(ctx.chat_id) is None:
            await ctx.reply("Режим тишины уже отключён")
            return
        await self.silenced.save()
        await ctx.reply("Режим тишины отключен")


class SilenceEnforcerFeature(Feature):
    silenced = collection("silenced_chats")

    @on_message
    async def enforce(self, ctx: FeatureContext) -> bool | None:
        if ctx.message is None:
            return False
        expires_at = self.silenced.get(ctx.chat_id)
        if expires_at is None:
            return False
        if expires_at <= datetime.now(timezone.utc):
            self.silenced.pop(ctx.chat_id)
            await self.silenced.save()
            return False
        try:
            await ctx.message.delete()
        except BaseException as error:
            logger.warning("Failed to delete message in silence mode: %s", error)
            return False
        return True
