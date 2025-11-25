import datetime
from dataclasses import dataclass
from math import ceil
from zoneinfo import ZoneInfo

from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark


TIMEZONE = ZoneInfo("Europe/Minsk")


@dataclass(kw_only=True)
@class_mark("generator/constant")
class ConstantGenerator(Generator):
    start: datetime.datetime
    period: datetime.timedelta

    def get_next(self, now):
        if self.start >= now:
            return self.start

        return self.start + self.period * ceil((now - self.start) / self.period)
