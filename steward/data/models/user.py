from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: int
    username: Optional[str] = None
