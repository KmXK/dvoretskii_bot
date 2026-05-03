import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from steward.delayed_action.watch import WatchDelayedAction
from steward.framework import Feature, FeatureContext, collection, subcommand
from steward.helpers.cake_price import cake_fetcher
from steward.helpers.webapp import get_webapp_keyboard

logger = logging.getLogger(__name__)


class WatchFeature(Feature):
    command = "watch"
    description = "Запустить/остановить часы в закрепленном сообщении"

    delayed_actions = collection("delayed_actions")

    @subcommand("", description="Toggle watch")
    async def toggle(self, ctx: FeatureContext):
        if ctx.message is None:
            return
        chat_id = ctx.chat_id
        watch_action = self.delayed_actions.find_one(
            lambda x: isinstance(x, WatchDelayedAction) and x.chat_id == chat_id
        )

        if watch_action is not None:
            try:
                await ctx.bot.unpin_chat_message(
                    chat_id=chat_id, message_id=watch_action.message_id,
                )
            except Exception as e:
                logger.warning(f"Failed to unpin message: {e}")
            self.delayed_actions.remove(watch_action)
            await self.delayed_actions.save()
            await ctx.reply("Часы остановлены")
            return

        now = datetime.now(tz=ZoneInfo("Europe/Minsk"))
        time_str = now.strftime("%d.%m.%Y %H:%M")
        cake = await cake_fetcher.get_status()
        if cake:
            time_str += f"\n{cake.format()}"
        sent_message = await ctx.message.reply_text(
            time_str,
            reply_markup=get_webapp_keyboard(
                ctx.bot, chat_id, is_private=ctx.message.chat.type == "private"
            ),
        )
        try:
            await ctx.bot.pin_chat_message(
                chat_id=chat_id, message_id=sent_message.message_id,
            )
        except Exception as e:
            logger.warning(f"Failed to pin message: {e}")
            await ctx.reply(
                "Не удалось закрепить сообщение. Возможно, у бота нет прав администратора."
            )
            return
        self.delayed_actions.add(
            WatchDelayedAction(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                is_private=ctx.message.chat.type == "private",
            )
        )
        await self.delayed_actions.save()
