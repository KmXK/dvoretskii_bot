import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from steward.delayed_action.base import DelayedAction, Generator
from steward.delayed_action.context import DelayedActionContext
from steward.helpers.cake_price import cake_fetcher
from steward.helpers.class_mark import class_mark
from steward.helpers.webapp import get_webapp_keyboard

logger = logging.getLogger(__name__)


@dataclass
@class_mark("generator/minute")
class MinuteGenerator(Generator):
    def get_next(self, now: datetime):
        next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return next_minute


@dataclass(kw_only=True)
@class_mark("delayed_action/watch")
class WatchDelayedAction(DelayedAction):
    generator: MinuteGenerator = field(
        default_factory=MinuteGenerator, init=False
    )

    chat_id: int
    message_id: int
    is_private: bool

    async def execute(self, context: DelayedActionContext):
        now = datetime.now(tz=ZoneInfo("Europe/Minsk"))
        time_str = now.strftime("%d.%m.%Y %H:%M")

        cake = await cake_fetcher.get_status()
        if cake:
            time_str += f"\n{cake.format()}"

        try:
            await context.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=time_str,
                reply_markup=get_webapp_keyboard(context.bot, self.chat_id, is_private=self.is_private),
            )
        except Exception as e:
            logger.warning(f"Failed to update watch message: {e}")
