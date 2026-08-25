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
    interest_percent: float = 1.0
    paid_since_interest: int = 0
    last_interest_delta: int = 0
    last_interest_percent_added: float = 0.0


@dataclass
class CurseParticipant:
    user_id: int
    subscribed_at: datetime
    last_done_at: datetime | None = None
    done_words_offset: int = 0
    source_chat_ids: list[int] = field(default_factory=list)
    interest_enabled: bool = True


@dataclass
class CurseStreak:
    """Глобальный пользовательский стрик полных дней без мата."""

    user_id: int
    days: int = 0
    last_finalized_date: str = ""
    last_curse_date: str = ""
    curses_on_last_curse_date: int = 0
    hourly_curse_date: str = ""
    hourly_curse_counts: list[int] = field(default_factory=lambda: [0] * 24)
