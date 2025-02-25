from dataclasses import dataclass

from steward.bot.context import BotContext


@dataclass
class DelayedActionContext(BotContext):
    pass
