import logging
from abc import abstractmethod
from dataclasses import dataclass

from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.base import Generator

logger = logging.getLogger(__name__)


@dataclass
class DelayedAction:
    generator: Generator

    @abstractmethod
    async def execute(self, context: DelayedActionContext):
        pass
