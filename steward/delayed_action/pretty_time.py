from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import product
from zoneinfo import ZoneInfo

from steward.delayed_action.base import DelayedAction, Generator
from steward.delayed_action.context import DelayedActionContext
from steward.helpers.class_mark import class_mark

pretty_times = [
    time(hour=h, minute=t, tzinfo=ZoneInfo("Europe/Minsk"))
    for h, t in [
        map(int, x.split(":"))
        for x in [
            "00:00",
            "11:11",
            "12:34",
            "15:28",
            "22:22",
        ]
    ]
]


@dataclass
@class_mark("generator/pretty_time")
class PrettyTimeGenerator(Generator):
    def get_next(self, now: datetime):
        times = [
            datetime.combine(d, t)
            for d, t in product(
                [date.today(), date.today() + timedelta(days=1)], pretty_times
            )
        ]
        times.sort()

        for t in times:
            if t >= now:
                return t


@dataclass
@class_mark("delayed_action/pretty_time")
class PrettyTimeDelayedAction(DelayedAction):
    chat_id: int
    generator: PrettyTimeGenerator = field(
        default_factory=PrettyTimeGenerator,
        init=False,
    )

    async def execute(self, context: DelayedActionContext):
        await context.bot.send_message(
            self.chat_id,
            datetime.strftime(datetime.now(tz=ZoneInfo("Europe/Minsk")), "%H:%M"),
        )
