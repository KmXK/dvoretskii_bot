from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    id: int
    username: Optional[str] = None
    chat_ids: list[int] = field(default_factory=list)
    monkeys: int = 100
    casino_last_bonus: float = 0
    stand_name: Optional[str] = None
    stand_description: Optional[str] = None
