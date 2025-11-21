import datetime
from dataclasses import dataclass
from math import ceil
from zoneinfo import ZoneInfo

from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark

TIMEZONE = ZoneInfo("Europe/Minsk")


@dataclass
@class_mark("generator/channel_subscription")
class ChannelSubscriptionGenerator(Generator):
    """Генератор для ежедневного выполнения в указанное время"""

    subscription_id: int  # ID подписки
    target_time: datetime.time
    start: datetime.datetime | None = None

    def get_next(self, now: datetime.datetime) -> datetime.datetime | None:
        # Приводим now к нужному timezone
        if now.tzinfo is None:
            now = now.replace(tzinfo=TIMEZONE)
        else:
            now = now.astimezone(TIMEZONE)

        # Если start не установлен, устанавливаем его на сегодня в указанное время
        if self.start is None:
            today = now.date()
            self.start = datetime.datetime.combine(today, self.target_time).replace(
                tzinfo=TIMEZONE
            )
            # Если время уже прошло сегодня, планируем на завтра
            if self.start <= now:
                self.start = self.start + datetime.timedelta(days=1)

        # Период - один день
        period = datetime.timedelta(days=1)

        # Если start еще не наступил, возвращаем его
        if self.start >= now:
            return self.start

        # Иначе вычисляем следующее время (каждый день в указанное время)
        return self.start + period * ceil((now - self.start) / period)
