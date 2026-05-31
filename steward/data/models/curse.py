from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CursePunishment:
    id: int
    coeff: int
    title: str
    interest_percent: float = 0.0
    selection_weight: float = 1.0


@dataclass
class CursePunishmentDay:
    date: str
    rule_id: int


@dataclass
class CursePunishmentDebt:
    id: int
    user_id: int
    rule_id: int
    punishment_count: int
    last_interest_applied_date: str


@dataclass
class CurseParticipant:
    user_id: int
    subscribed_at: datetime
    last_done_at: datetime | None = None
    done_words_offset: int = 0
    source_chat_ids: list[int] = field(default_factory=list)
