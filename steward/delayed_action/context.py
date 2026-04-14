from dataclasses import dataclass

from steward.bot.context import BotContext
from steward.metrics.base import MetricsEngine


@dataclass
class DelayedActionContext(BotContext):
    metrics: MetricsEngine
