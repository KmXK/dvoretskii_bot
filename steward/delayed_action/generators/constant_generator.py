import datetime
from dataclasses import dataclass
from math import ceil

from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark


@dataclass
@class_mark("generator", "constant")
class ConstantGenerator(Generator):
    start: datetime.datetime  # TODO: Fix timezone
    period: datetime.timedelta

    def get_next(self, now):
        if self.start >= now:
            return self.start

        return self.start + self.period * ceil((now - self.start) / self.period)
