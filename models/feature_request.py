from dataclasses import dataclass
from typing import Optional
import uuid


@dataclass
class FeatureRequest:
    text: str
    author_id: int
    author_name: str
    priority: int = 100
    id: str = uuid.uuid4().hex