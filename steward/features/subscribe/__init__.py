from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from steward.data.models.channel_subscription import ChannelSubscription
from steward.delayed_action.channel_subscription import (
    ChannelSubscriptionDelayedAction,
    get_posts_from_html,
)
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.features.subscribe.add_session import (
    CollectChannelPostStep,
    CollectTimesStep,
    VerifyChannelStep,
)
from steward.framework import (
    Feature,
    FeatureContext,
    collection,
    paginated,
    step,
    subcommand,
    wizard,
)
from steward.helpers.formats import escape_markdown, format_lined_list
from steward.helpers.tg_update_helpers import get_message


_TIMEZONE = ZoneInfo("Europe/Minsk")


class SubscribeFeature(Feature):
    command = "subscribe"
    description = "Управление подписками на каналы"
    help_examples = [
        "«покажи подписки» → /subscribe",
        "«добавь подписку» → /subscribe add",
        "«удали подписку 3» → /subscribe remove 3",
    ]

    channel_subscriptions = collection("channel_subscriptions")
    delayed_actions = collection("delayed_actions")

    @subcommand("", description="Список подписок этого чата")
    async def list_subscriptions(self, ctx: FeatureContext):
        if not self.channel_subscriptions.filter(chat_id=ctx.chat_id):
            await ctx.reply("В этом чате нет подписок на каналы")
            return
        await self.paginate(ctx, "subs", metadata=str(ctx.chat_id))

    @subcommand("add", description="Добавить подписку (запускает сессию)")
    async def add(self, ctx: FeatureContext):
        await self.start_wizard("subscribe:add", ctx)

    @subcommand("remove <id:int>", description="Удалить подписку по ID")
    async def remove(self, ctx: FeatureContext, id: int):
        chat_id = ctx.chat_id
        subscription = self.channel_subscriptions.find_by(id=id, chat_id=chat_id)
        if subscription is None:
            await ctx.reply("Подписка с таким ID не найдена в этом чате")
            return

        self.channel_subscriptions.remove(subscription)
        actions_to_remove = [
            action
            for action in self.delayed_actions
            if isinstance(action, ChannelSubscriptionDelayedAction)
            and action.subscription_id == id
        ]
        for action in actions_to_remove:
            self.delayed_actions.remove(action)

        await self.channel_subscriptions.save()

        channel_display = (
            f"@{subscription.channel_username}"
            if subscription.channel_username
            else f"ID {subscription.channel_id}"
        )
        await ctx.reply(
            f"Подписка на канал {channel_display} (ID: {id}) удалена"
        )

    @paginated("subs", per_page=15, header="Подписки на каналы")
    def subs_page(self, ctx: FeatureContext, metadata: str):
        chat_id = int(metadata)
        items = self.channel_subscriptions.filter(chat_id=chat_id)

        def render(batch):
            def fmt(sub: ChannelSubscription) -> str:
                times_str = ", ".join([t.strftime("%H:%M") for t in sub.times])
                channel_display = (
                    f"@{sub.channel_username}"
                    if sub.channel_username
                    else f"ID {sub.channel_id}"
                )
                return f"{escape_markdown(channel_display)} ({sub.id}) - {times_str}"

            return format_lined_list(
                items=[(sub.id, fmt(sub)) for sub in batch],
                delimiter=". ",
            )

        return items, render

    @wizard(
        "subscribe:add",
        step("channel_info", CollectChannelPostStep()),
        step("channel_verified", VerifyChannelStep()),
        step("times", CollectTimesStep()),
    )
    async def on_add_done(
        self, ctx: FeatureContext, channel_info, channel_verified=None, times=None, **state
    ):
        message = get_message(ctx.update)
        if not state.get("channel_confirmed", False):
            await message.chat.send_message("Подписка отменена")
            return

        chat_id = message.chat_id
        channel_id = channel_info["channel_id"]
        channel_username = channel_info["channel_username"]

        if not times:
            await message.chat.send_message(
                "Необходимо указать хотя бы одно время отправки постов"
            )
            return

        existing = self.channel_subscriptions.find_by(
            channel_id=channel_id, chat_id=chat_id
        )
        if existing is not None:
            await message.chat.send_message(
                "Подписка на этот канал в этом чате уже существует"
            )
            return

        posts = await get_posts_from_html(channel_username)
        last_post_id = max(post["id"] for post in posts) if posts else 0

        subscription = self.channel_subscriptions.add(
            ChannelSubscription(
                id=0,
                channel_id=channel_id,
                channel_username=channel_username,
                chat_id=chat_id,
                times=times,
                last_post_id=last_post_id,
            )
        )

        now = datetime.now(_TIMEZONE)
        for t in times:
            today = now.date()
            start = datetime.combine(today, t).replace(tzinfo=_TIMEZONE)
            if start <= now:
                start = start + timedelta(days=1)

            self.delayed_actions.add(
                ChannelSubscriptionDelayedAction(
                    subscription_id=subscription.id,
                    generator=ConstantGenerator(
                        start=start,
                        period=timedelta(days=1),
                    ),
                )
            )

        await self.channel_subscriptions.save()

        channel_display = channel_info.get(
            "channel_username", f"ID {channel_info['channel_id']}"
        )
        await message.chat.send_message(
            f"Подписка на канал @{channel_display} успешно создана! "
            f"ID подписки: {subscription.id}\n"
            f"Посты будут отправляться в "
            f"{', '.join([t.strftime('%H:%M') for t in times])}"
        )
