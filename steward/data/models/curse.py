from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CursePunishment:
    id: int
    coeff: int
    title: str


@dataclass
class CurseParticipant:
    user_id: int
    subscribed_at: datetime
    last_done_at: datetime | None = None
    source_chat_ids: list[int] = field(default_factory=list)
