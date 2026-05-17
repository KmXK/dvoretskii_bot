from dataclasses import dataclass


@dataclass
class Incident:
    id: int
    chat_id: int
    author_id: int
    text: str
    created_at: float
