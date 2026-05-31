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
    """Сессия игры 1v1: набор партий между двумя игроками.

    sport — вид спорта с ракеткой: "table_tennis" (наст. теннис, дефолт) или
    "squash". Счёт партии у обоих PAR до 11 (разница ≥2); отличается правило
    подачи (см. steward.tennis.engine.next_first_server).
    """
    id: int
    chat_id: int
    player_a_id: int
    player_b_id: int
    started_at: datetime
    sport: str = "table_tennis"
    # Падел — парный (2v2). Напарники сторон A/B; None для одиночных спортов.
    player_a2_id: int | None = None
    player_b2_id: int | None = None
    # Конфиг падела (для остальных спортов игнорируется).
    golden_point: bool = True   # «золотой мяч» при 40:40 вместо advantage
    sets_to_win: int = 2        # best-of-N сетов (2 = best-of-3)
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
    first_server: str = "a"   # кто подаёт первым в следующей партии
    # Кто подавал первым в самой первой партии сессии. Нужен, чтобы корректно
    # пересчитывать first_server из списка партий (в т.ч. при undo до пустого).
    initial_server: str = "a"
    # Каждые N партий первая подача переходит к другому игроку. По правилам
    # настольного тенниса обычно 2 партии «свои подачи» подряд → дефолт 2.
    serve_streak: int = 2
    # Legacy: использовалось для «сетов» (N партий = 1 сет) — убрано из UI,
    # поля остаются для совместимости со старыми записями в db.json.
    set_size: int = 0
    sets_announced: int = 0
