from pyrate_limiter import BucketFullException

from steward.framework import Feature, FeatureContext, collection, subcommand
from steward.helpers.duration import format_timedelta, parse_duration
from steward.helpers.limiter import Duration, check_limit
from steward.joke_checker import generate_joke

_OFF_TOKENS = {"off", "stop", "cancel", "0", "выкл"}
_RATE_GLOBAL = "joke_now_global"
_RATE_USER = "joke_now_user"


class JokeFeature(Feature):
    command = "joke"
    only_admin = True
    description = "Анекдот при долгом молчании"
    help_examples = [
        "«присылать анекдот при молчании 12 часов» → /joke 12h",
        "«отправить анекдот сейчас» → /joke now",
        "«выключить» → /joke",
    ]

    joke_settings = collection("joke_settings")

    @subcommand("now", description="Отправить анекдот прямо сейчас")
    async def now(self, ctx: FeatureContext):
        try:
            check_limit(_RATE_GLOBAL, 5, Duration.MINUTE)
            check_limit(_RATE_USER, 2, Duration.MINUTE, name=str(ctx.user_id))
        except BucketFullException:
            await ctx.reply("Подожди немного, слишком много запросов на анекдоты", markdown=False)
            return
        placeholder = await ctx.reply("Придумываю…", markdown=False)
        joke = await generate_joke()
        if not joke:
            if placeholder:
                await placeholder.edit_text("Не получилось придумать анекдот, попробуй позже")
            return
        if placeholder:
            await placeholder.edit_text(joke)
        else:
            await ctx.reply(joke, markdown=False)

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
