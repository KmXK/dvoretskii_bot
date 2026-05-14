from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TennisMatch:
    """Одна партия (game to 11 c deuce). winner = 'a' | 'b'."""
    started_at: datetime
    winner: str
    ended_at: datetime | None = None
    score_a: int | None = None
    score_b: int | None = None


@dataclass
class TennisSession:
    """Сессия игры 1v1: набор партий между двумя игроками."""
    id: int
    chat_id: int
    player_a_id: int
    player_b_id: int
    started_at: datetime
    ended_at: datetime | None = None
    last_activity_at: datetime = field(default_factory=datetime.now)
    matches: list[TennisMatch] = field(default_factory=list)
    is_aggregate_only: bool = False
    closed_reason: str = ""  # "manual" | "timeout" | "" пока активна
    note: str = ""
    initiator_id: int = 0
    # Лайв-состояние текущей (незаконченной) партии — для подачи и точечного учёта
    current_score_a: int = 0
    current_score_b: int = 0
    points_log: list[str] = field(default_factory=list)  # 'a'|'b' по поинтам текущей партии
    first_server: str = "a"   # кто подавал первым в текущей партии
    set_size: int = 0          # размер сета в партиях, 0 = без сетов
    sets_announced: int = 0    # сколько границ сета уже озвучено
