from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    id: int
    username: Optional[str] = None
    chat_ids: list[int] = field(default_factory=list)
