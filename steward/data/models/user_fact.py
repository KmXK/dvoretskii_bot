from dataclasses import dataclass


@dataclass
class UserFact:
    user_id: int
    text: str
    created_at: float  # unix timestamp seconds
