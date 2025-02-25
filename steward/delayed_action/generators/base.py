import datetime
from abc import abstractmethod
from dataclasses import dataclass
from typing import Awaitable

type GeneratorResponse = datetime.datetime | None


@dataclass
class Generator:
    @abstractmethod
    def get_next(
        self,
        now: datetime.datetime,
    ) -> GeneratorResponse | Awaitable[GeneratorResponse]:
        pass
