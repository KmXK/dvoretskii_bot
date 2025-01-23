import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class FeatureRequest:
    text: str
    author_id: int
    author_name: str
    creation_timestamp: Optional[float]
    message_id: Optional[int]
    chat_id: Optional[int]
    priority: int = 100
    id: str = uuid.uuid4().hex