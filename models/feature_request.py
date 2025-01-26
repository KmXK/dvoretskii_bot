from dataclasses import dataclass
from typing import Optional


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
    done_timestamp: Optional[float] = None
    deny_timestamp: Optional[float] = None
