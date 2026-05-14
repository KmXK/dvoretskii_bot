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


def player_stats(sessions: list[TennisSession], user_id: int) -> PlayerStats:
    """Агрегируем по всем сессиям, где user_id участвовал."""
    relevant = [
        s for s in sessions
        if s.player_a_id == user_id or s.player_b_id == user_id
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
