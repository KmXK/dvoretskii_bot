import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from steward.bot.context import ChatBotContext
from steward.delayed_action.watch import WatchDelayedAction
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.cake_price import cake_fetcher
from steward.helpers.webapp import get_webapp_keyboard

logger = logging.getLogger(__name__)


@CommandHandler("watch")
class WatchHandler(Handler):
    async def chat(self, context: ChatBotContext):
        chat_id = context.message.chat_id

        watch_action = next(
            filter(
                lambda x: (isinstance(x, WatchDelayedAction) and x.chat_id == chat_id),
                self.repository.db.delayed_actions,
            ),
            None,
        )

        if watch_action is not None:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=chat_id,
                    message_id=watch_action.message_id,
                )
            except Exception as e:
                logger.warning(f"Failed to unpin message: {e}")

            self.repository.db.delayed_actions.remove(watch_action)
            await self.repository.save()

            await context.message.reply_text("Часы остановлены")
            return True

        now = datetime.now(tz=ZoneInfo("Europe/Minsk"))
        time_str = now.strftime("%d.%m.%Y %H:%M")

        cake = await cake_fetcher.get_status()
        if cake:
            time_str += f"\n{cake.format()}"

        sent_message = await context.message.reply_text(
            time_str,
            reply_markup=get_webapp_keyboard(context.bot, chat_id, is_private=context.message.chat.type == "private"),
        )

        try:
            await context.bot.pin_chat_message(
                chat_id=chat_id,
                message_id=sent_message.message_id,
            )
        except Exception as e:
            logger.warning(f"Failed to pin message: {e}")
            await context.message.reply_text(
                "Не удалось закрепить сообщение. Возможно, у бота нет прав администратора."
            )
            return True

        watch_action = WatchDelayedAction(
            chat_id=chat_id,
            message_id=sent_message.message_id,
        )
        self.repository.db.delayed_actions.append(watch_action)
        await self.repository.save()

        return True

    def help(self) -> str | None:
        return "/watch - запустить/остановить часы в закрепленном сообщении"
