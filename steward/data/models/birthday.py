from dataclasses import dataclass


@dataclass
class Birthday:
    name: str
    day: int
    month: int
    chat_id: int
    year: int | None = None
    description: str = ""
