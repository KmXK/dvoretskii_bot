from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class FeatureRequestStatus(IntEnum):
    OPEN = 0
    DONE = 1
    DENIED = 2


@dataclass
class FeatureRequestChange:
    author_id: int
    timestamp: float
    message_id: int
    status: FeatureRequestStatus = field(default_factory=FeatureRequestStatus)


@dataclass
class FeatureRequest:
    id: int
    text: str
    author_id: int
    author_name: str
    creation_timestamp: Optional[float]
    message_id: Optional[int]
    chat_id: Optional[int]

    priority: int = 100
    history: list[FeatureRequestChange] = field(default_factory=list)

    @property
    def status(self) -> FeatureRequestStatus:
        if len(self.history) == 0:
            return FeatureRequestStatus.OPEN
        return self.history[-1].status
