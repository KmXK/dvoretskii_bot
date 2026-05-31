"""Чистые функции для теннисной модели: валидация партий, агрегации, статистика.

Не содержит I/O и зависимостей от Telegram/aiohttp — тестируется напрямую.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime

from steward.data.models.tennis import TennisMatch, TennisSession


SIDE_A = "a"
SIDE_B = "b"

# ── виды спорта с ракеткой ────────────────────────────────────────────────────
# Счёт партии у настольного тенниса и сквоша одинаковый (PAR до 11, разница ≥2),
# отличается лишь правило подачи (см. next_first_server). Падел будет добавлен
# отдельно — у него теннисный счёт и пары 2v2.
SPORT_TABLE_TENNIS = "table_tennis"
SPORT_SQUASH = "squash"
SPORT_PADEL = "padel"
DEFAULT_SPORT = SPORT_TABLE_TENNIS

# Спорты с «партийным» счётом PAR-до-11 (тап=очко сворачивается в один счёт
# партии). Падел сюда НЕ входит — у него теннисная иерархия очки→гейм→сет.
PAR_SPORTS = (SPORT_TABLE_TENNIS, SPORT_SQUASH)

SPORTS: dict[str, dict[str, str]] = {
    SPORT_TABLE_TENNIS: {
        "label": "настольный теннис",
        "label_short": "теннис",
        "genitive": "настольного тенниса",
        "emoji": "🏓",
    },
    SPORT_SQUASH: {
        "label": "сквош",
        "label_short": "сквош",
        "genitive": "сквоша",
        "emoji": "🎾",
    },
    SPORT_PADEL: {
        "label": "падел",
        "label_short": "падел",
        "genitive": "падела",
        "emoji": "🎾",
    },
}


def is_padel(sport: str | None) -> bool:
    return normalize_sport(sport) == SPORT_PADEL


def is_team_sport(sport: str | None) -> bool:
    """Парный (2v2) спорт. Сейчас только падел."""
    return is_padel(sport)


def normalize_sport(sport: str | None) -> str:
    """Любое неизвестное/None значение → дефолтный спорт. Защищает старые записи."""
    return sport if sport in SPORTS else DEFAULT_SPORT


def sport_meta(sport: str | None) -> dict[str, str]:
    return SPORTS[normalize_sport(sport)]


def next_first_server(
    sport: str | None,
    matches: list[TennisMatch],
    *,
    initial_server: str,
    serve_streak: int,
) -> str:
    """Кто подаёт первым в предстоящей партии — по правилам конкретного спорта.

    Чистая функция: пересчитывается целиком из списка сыгранных партий, поэтому
    одинаково корректна и после записи новой партии, и после undo.

    - настольный теннис: первая подача переходит к другому игроку каждые
      ``serve_streak`` партий (отсчёт от ``initial_server``).
    - сквош: следующую партию начинает подавать победитель предыдущей; если
      партий ещё нет — подаёт ``initial_server``.
    """
    base = initial_server if initial_server in (SIDE_A, SIDE_B) else SIDE_A
    if normalize_sport(sport) == SPORT_SQUASH:
        return matches[-1].winner if matches else base
    streak = max(1, serve_streak or 2)
    flips = len(matches) // streak
    if flips % 2 == 0:
        return base
    return SIDE_B if base == SIDE_A else SIDE_A


def is_valid_party_score(score_a: int, score_b: int) -> bool:
    """11 очков у победителя минимум, разница ≥2.

    Соответствует правилу: до 11; при 10:10 играем до разницы в 2.
    11:0..11:9 — да; 11:10 — нет; 12:10 — да; 13:11 — да; 12:11 — нет.
    """
    if score_a < 0 or score_b < 0:
        return False
    if score_a == score_b:
        return False
    hi, lo = max(score_a, score_b), min(score_a, score_b)
    return hi >= 11 and hi - lo >= 2


def derive_winner(score_a: int, score_b: int) -> str:
    return SIDE_A if score_a > score_b else SIDE_B


# ── point-by-point (тап = очко) ───────────────────────────────────────────────
# Базовая цель партии — 11 очков, при 10:10 играем до разницы в 2. Та же модель,
# что и is_valid_party_score, но для незавершённого («живого») счёта.
PARTY_TARGET = 11


def is_party_complete(score_a: int, score_b: int, *, target: int = PARTY_TARGET) -> bool:
    """Закончилась ли партия при текущем счёте: кто-то набрал target и ведёт ≥2.

    11:9 — да; 11:10 — нет (deuce); 12:10 — да; 13:11 — да; 12:11 — нет.
    """
    hi, lo = max(score_a, score_b), min(score_a, score_b)
    return hi >= target and hi - lo >= 2


def party_point_to_side(points_log: list[str]) -> tuple[int, int]:
    """Свернуть журнал поинтов ('a'/'b') в текущий счёт партии (a, b)."""
    a = sum(1 for p in points_log if p == SIDE_A)
    b = sum(1 for p in points_log if p == SIDE_B)
    return a, b


def current_point_server(
    sport: str | None,
    score_a: int,
    score_b: int,
    *,
    party_first_server: str,
) -> str:
    """Кто подаёт следующий розыгрыш в текущей партии (для индикатора на табло).

    - настольный теннис: подача переходит каждые 2 очка; при счёте 10:10
      (deuce) — каждое очко.
    - сквош (PAR): подаёт тот, кто выиграл прошлый розыгрыш; в начале партии —
      ``party_first_server``.
    """
    base = party_first_server if party_first_server in (SIDE_A, SIDE_B) else SIDE_A
    other = SIDE_B if base == SIDE_A else SIDE_A

    if normalize_sport(sport) == SPORT_SQUASH:
        if score_a == score_b == 0:
            return base
        return SIDE_A if score_a > score_b else (SIDE_B if score_b > score_a else base)

    total = score_a + score_b
    deuce = score_a >= 10 and score_b >= 10
    blocks = total if deuce else total // 2
    return base if blocks % 2 == 0 else other


# ── падел: теннисный счёт очки→гейм→сет→матч ──────────────────────────────────
# Падел считается как теннис: в гейме очки 0/15/30/40 (+ Ad или «золотой мяч»),
# сет — до 6 геймов с разницей ≥2, при 6:6 тай-брейк до 7 (разница ≥2), матч —
# best-of-N сетов. Всё состояние реконструируется из points_log (список 'a'/'b'),
# поэтому undo = снять последний поинт и пересчитать. Чистая функция, без I/O.

PADEL_GAMES_PER_SET = 6
PADEL_TIEBREAK_TO = 7
PADEL_DEFAULT_SETS_TO_WIN = 2   # best-of-3
_POINT_NAMES = ("0", "15", "30", "40")


@dataclass
class PadelState:
    sets_a: int
    sets_b: int
    games_a: int
    games_b: int
    points_a: int                 # сырые очки текущего гейма/тай-брейка
    points_b: int
    point_label_a: str            # "0"/"15"/"30"/"40"/"Ad" или число (тай-брейк)
    point_label_b: str
    in_tiebreak: bool
    completed_sets: list[tuple[int, int]]   # счёт законченных сетов (геймы)
    match_complete: bool
    winner: str | None


def _padel_point_labels(pa: int, pb: int, golden: bool, in_tb: bool) -> tuple[str, str]:
    if in_tb:
        return str(pa), str(pb)
    if not golden and pa >= 3 and pb >= 3:
        if pa == pb:
            return "40", "40"
        return ("Ad", "40") if pa > pb else ("40", "Ad")
    return _POINT_NAMES[min(pa, 3)], _POINT_NAMES[min(pb, 3)]


def _padel_game_winner(pa: int, pb: int, golden: bool) -> str | None:
    """Кто выиграл гейм при сырых очках pa:pb. golden — «золотой мяч» при 40:40."""
    if golden:
        # Очки 0,15,30,40 → 4-е очко всегда решающее (при 40:40 — punto de oro).
        if pa >= 4:
            return SIDE_A
        if pb >= 4:
            return SIDE_B
        return None
    if pa >= 4 and pa - pb >= 2:
        return SIDE_A
    if pb >= 4 and pb - pa >= 2:
        return SIDE_B
    return None


def padel_state(
    points_log: list[str],
    *,
    golden_point: bool = True,
    sets_to_win: int = PADEL_DEFAULT_SETS_TO_WIN,
    games_per_set: int = PADEL_GAMES_PER_SET,
    tiebreak_to: int = PADEL_TIEBREAK_TO,
) -> PadelState:
    """Развернуть журнал поинтов в полное состояние паделльного матча."""
    sets_a = sets_b = 0
    completed_sets: list[tuple[int, int]] = []
    games_a = games_b = 0
    pa = pb = 0
    in_tb = False
    winner: str | None = None

    def finalize_set(ga: int, gb: int) -> None:
        nonlocal sets_a, sets_b, games_a, games_b, pa, pb, in_tb, winner
        completed_sets.append((ga, gb))
        if ga > gb:
            sets_a += 1
        else:
            sets_b += 1
        games_a = games_b = pa = pb = 0
        in_tb = False
        if sets_a >= sets_to_win:
            winner = SIDE_A
        elif sets_b >= sets_to_win:
            winner = SIDE_B

    for p in points_log:
        if winner is not None:
            break
        if p == SIDE_A:
            pa += 1
        elif p == SIDE_B:
            pb += 1
        else:
            continue

        if in_tb:
            hi, lo = max(pa, pb), min(pa, pb)
            if hi >= tiebreak_to and hi - lo >= 2:
                # победитель тай-брейка забирает сет 7:6
                if pa > pb:
                    finalize_set(games_a + 1, games_b)
                else:
                    finalize_set(games_a, games_b + 1)
            continue

        gw = _padel_game_winner(pa, pb, golden_point)
        if gw is None:
            continue
        if gw == SIDE_A:
            games_a += 1
        else:
            games_b += 1
        pa = pb = 0

        if games_a >= games_per_set and games_a - games_b >= 2:
            finalize_set(games_a, games_b)
        elif games_b >= games_per_set and games_b - games_a >= 2:
            finalize_set(games_a, games_b)
        elif games_a == games_per_set and games_b == games_per_set:
            in_tb = True

    la, lb = _padel_point_labels(pa, pb, golden_point, in_tb)
    return PadelState(
        sets_a=sets_a,
        sets_b=sets_b,
        games_a=games_a,
        games_b=games_b,
        points_a=pa,
        points_b=pb,
        point_label_a=la,
        point_label_b=lb,
        in_tiebreak=in_tb,
        completed_sets=completed_sets,
        match_complete=winner is not None,
        winner=winner,
    )


def padel_server_side(points_log: list[str], party_first_server: str, **kwargs) -> str:
    """Приблизительный индикатор: подача в паделе переходит к другой паре каждый
    гейм. Считаем по чётности числа сыгранных геймов (тай-брейк — как один гейм)."""
    base = party_first_server if party_first_server in (SIDE_A, SIDE_B) else SIDE_A
    other = SIDE_B if base == SIDE_A else SIDE_A
    st = padel_state(points_log, **kwargs)
    played_games = sum(ga + gb for ga, gb in st.completed_sets) + st.games_a + st.games_b
    return base if played_games % 2 == 0 else other


def session_wins(session: TennisSession) -> tuple[int, int]:
    a = sum(1 for m in session.matches if m.winner == SIDE_A)
    b = sum(1 for m in session.matches if m.winner == SIDE_B)
    return a, b


def session_duration_seconds(session: TennisSession) -> float | None:
    if session.ended_at is None:
        return None
    return (session.ended_at - session.started_at).total_seconds()


def match_durations(session: TennisSession) -> list[float]:
    out: list[float] = []
    for m in session.matches:
        if m.ended_at is None:
            continue
        out.append((m.ended_at - m.started_at).total_seconds())
    return out


def gaps_between_matches(session: TennisSession) -> list[float]:
    """Секунды между концом партии i и началом партии i+1."""
    out: list[float] = []
    matches = session.matches
    for i in range(1, len(matches)):
        prev = matches[i - 1]
        cur = matches[i]
        if prev.ended_at is None:
            continue
        delta = (cur.started_at - prev.ended_at).total_seconds()
        if delta < 0:
            continue
        out.append(delta)
    return out


@dataclass
class PlayerStats:
    user_id: int
    sessions: int
    matches: int
    wins: int
    losses: int
    win_rate: float
    median_matches_per_session: float | None
    median_point_diff: float | None       # медиана разности очков в выигранных партиях
    median_match_duration_s: float | None
    median_gap_s: float | None
    longest_win_streak: int


def player_stats(
    sessions: list[TennisSession],
    user_id: int,
    sport: str | None = None,
) -> PlayerStats:
    """Агрегируем по всем сессиям, где user_id участвовал.

    Если задан ``sport`` — учитываем только сессии этого вида спорта (нужно,
    чтобы статистика тенниса и сквоша не смешивалась)."""
    relevant = [
        s for s in sessions
        if (s.player_a_id == user_id or s.player_b_id == user_id)
        and (sport is None or normalize_sport(getattr(s, "sport", None)) == normalize_sport(sport))
    ]
    matches_total = 0
    wins = 0
    losses = 0
    matches_per_session: list[int] = []
    point_diffs: list[int] = []
    durations: list[float] = []
    gaps: list[float] = []

    longest_streak = 0
    current_streak = 0

    sorted_sessions = sorted(relevant, key=lambda s: s.started_at)

    for s in sorted_sessions:
        side = SIDE_A if s.player_a_id == user_id else SIDE_B
        matches_total += len(s.matches)
        matches_per_session.append(len(s.matches))

        for m in s.matches:
            if m.winner == side:
                wins += 1
                current_streak += 1
                if current_streak > longest_streak:
                    longest_streak = current_streak
                if m.score_a is not None and m.score_b is not None:
                    point_diffs.append(abs(m.score_a - m.score_b))
            else:
                losses += 1
                current_streak = 0

            if m.started_at is not None and m.ended_at is not None:
                durations.append((m.ended_at - m.started_at).total_seconds())

        if not s.is_aggregate_only:
            gaps.extend(gaps_between_matches(s))

    win_rate = wins / matches_total if matches_total else 0.0

    return PlayerStats(
        user_id=user_id,
        sessions=len(relevant),
        matches=matches_total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        median_matches_per_session=statistics.median(matches_per_session) if matches_per_session else None,
        median_point_diff=statistics.median(point_diffs) if point_diffs else None,
        median_match_duration_s=statistics.median(durations) if durations else None,
        median_gap_s=statistics.median(gaps) if gaps else None,
        longest_win_streak=longest_streak,
    )


def aggregate_session_matches(
    started_at: datetime,
    wins_a: int,
    wins_b: int,
) -> list[TennisMatch]:
    """Создаёт N синтетических партий для агрегатного импорта без детальных счетов."""
    out: list[TennisMatch] = []
    for _ in range(max(0, int(wins_a))):
        out.append(TennisMatch(started_at=started_at, ended_at=started_at, winner=SIDE_A))
    for _ in range(max(0, int(wins_b))):
        out.append(TennisMatch(started_at=started_at, ended_at=started_at, winner=SIDE_B))
    return out
