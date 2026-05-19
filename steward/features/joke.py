from steward.framework import Feature, FeatureContext, collection, subcommand
from steward.helpers.duration import format_timedelta, parse_duration

_OFF_TOKENS = {"off", "stop", "cancel", "0", "выкл"}


class JokeFeature(Feature):
    command = "joke"
    only_admin = True
    description = "Анекдот при долгом молчании"
    help_examples = [
        "«присылать анекдот при молчании 12 часов» → /joke 12h",
        "«выключить» → /joke",
    ]

    joke_settings = collection("joke_settings")

    @subcommand("", description="Выключить автоматические анекдоты")
    async def off_default(self, ctx: FeatureContext):
        await self._off(ctx)

    @subcommand("<arg:rest>", description="Включить при молчании N времени или выключить", catchall=True)
    async def toggle(self, ctx: FeatureContext, arg: str):
        if arg.strip().lower() in _OFF_TOKENS:
            await self._off(ctx)
            return
        delta = parse_duration(arg.strip().lower())
        if delta is None:
            await ctx.reply(
                "Не получилось распознать время. Используй формат вида 10m, 2h30m, 12h."
            )
            return
        self.joke_settings.set(ctx.chat_id, delta)
        await self.joke_settings.save()
        await ctx.reply(
            f"Буду присылать анекдот, если в чате не было сообщений {format_timedelta(delta)}."
        )

    async def _off(self, ctx: FeatureContext):
        if self.joke_settings.pop(ctx.chat_id) is None:
            await ctx.reply("Автоматические анекдоты и так выключены")
            return
        await self.joke_settings.save()
        await ctx.reply("Автоматические анекдоты выключены")
