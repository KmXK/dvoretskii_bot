from datetime import datetime, timedelta

import pytest

from steward.data.models.tennis import TennisMatch, TennisSession
from steward.tennis.engine import (
    SIDE_A,
    SIDE_B,
    aggregate_session_matches,
    derive_winner,
    gaps_between_matches,
    is_valid_party_score,
    match_durations,
    player_stats,
    session_wins,
)


# ── валидация партии ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "a,b,ok",
    [
        (11, 0, True),
        (11, 9, True),
        (11, 10, False),    # deuce ещё не разошёлся
        (12, 10, True),
        (12, 11, False),    # разница 1 — продолжаем
        (13, 11, True),
        (15, 13, True),
        (0, 11, True),
        (10, 12, True),
        (11, 11, False),    # ничейный счёт невозможен
        (5, 3, False),
        (10, 9, False),     # никто не добрал 11
        (-1, 11, False),
        (11, -1, False),
    ],
)
def test_is_valid_party_score(a: int, b: int, ok: bool):
    assert is_valid_party_score(a, b) is ok


def test_derive_winner():
    assert derive_winner(11, 7) == SIDE_A
    assert derive_winner(7, 11) == SIDE_B
    assert derive_winner(13, 11) == SIDE_A


# ── агрегации по сессии ───────────────────────────────────────────────────────

def _now():
    return datetime(2026, 5, 14, 18, 0, 0)


def _session(matches: list[TennisMatch], **kwargs) -> TennisSession:
    started = matches[0].started_at if matches else _now()
    return TennisSession(
        id=1,
        chat_id=-100,
        player_a_id=1001,
        player_b_id=2002,
        started_at=started,
        matches=matches,
        **kwargs,
    )


def test_session_wins_empty():
    assert session_wins(_session([])) == (0, 0)


def test_session_wins_counts_winners():
    t = _now()
    matches = [
        TennisMatch(started_at=t, winner=SIDE_A),
        TennisMatch(started_at=t, winner=SIDE_A),
        TennisMatch(started_at=t, winner=SIDE_B),
    ]
    assert session_wins(_session(matches)) == (2, 1)


def test_match_durations_skips_unfinished():
    t = _now()
    matches = [
        TennisMatch(started_at=t, ended_at=t + timedelta(minutes=5), winner=SIDE_A),
        TennisMatch(started_at=t + timedelta(minutes=10), winner=SIDE_B),  # без ended_at
        TennisMatch(started_at=t + timedelta(minutes=20),
                    ended_at=t + timedelta(minutes=27), winner=SIDE_B),
    ]
    assert match_durations(_session(matches)) == [300.0, 420.0]


def test_gaps_between_matches():
    t = _now()
    m1 = TennisMatch(started_at=t, ended_at=t + timedelta(minutes=4), winner=SIDE_A)
    m2 = TennisMatch(started_at=t + timedelta(minutes=6),
                     ended_at=t + timedelta(minutes=10), winner=SIDE_B)
    m3 = TennisMatch(started_at=t + timedelta(minutes=15),
                     ended_at=t + timedelta(minutes=20), winner=SIDE_A)
    assert gaps_between_matches(_session([m1, m2, m3])) == [120.0, 300.0]


# ── aggregate_session_matches ────────────────────────────────────────────────

def test_aggregate_session_matches():
    t = _now()
    matches = aggregate_session_matches(t, wins_a=5, wins_b=3)
    assert len(matches) == 8
    winners = [m.winner for m in matches]
    assert winners.count(SIDE_A) == 5
    assert winners.count(SIDE_B) == 3
    assert all(m.score_a is None and m.score_b is None for m in matches)
    assert all(m.started_at == t and m.ended_at == t for m in matches)


def test_aggregate_session_matches_handles_zeros():
    assert aggregate_session_matches(_now(), 0, 0) == []
    assert len(aggregate_session_matches(_now(), 3, 0)) == 3


# ── player_stats ─────────────────────────────────────────────────────────────

def _build_detailed_session(
    sid: int, p_a: int, p_b: int, score_pairs: list[tuple[int, int]], start: datetime
) -> TennisSession:
    matches = []
    cur = start
    for sa, sb in score_pairs:
        ended = cur + timedelta(minutes=5)
        matches.append(TennisMatch(
            started_at=cur,
            ended_at=ended,
            winner=SIDE_A if sa > sb else SIDE_B,
            score_a=sa,
            score_b=sb,
        ))
        cur = ended + timedelta(minutes=2)
    return TennisSession(
        id=sid,
        chat_id=-100,
        player_a_id=p_a,
        player_b_id=p_b,
        started_at=start,
        ended_at=cur,
        matches=matches,
    )


def test_player_stats_basic():
    user = 1001
    other = 2002
    s1 = _build_detailed_session(
        1, user, other,
        [(11, 7), (11, 9), (8, 11)],  # user выиграл 2 из 3
        datetime(2026, 5, 10, 18, 0),
    )
    s2 = _build_detailed_session(
        2, other, user,
        [(11, 4), (9, 11), (11, 8)],  # user (side B) выиграл 1 из 3
        datetime(2026, 5, 11, 19, 0),
    )

    stats = player_stats([s1, s2], user)

    assert stats.user_id == user
    assert stats.sessions == 2
    assert stats.matches == 6
    assert stats.wins == 3
    assert stats.losses == 3
    assert stats.win_rate == 0.5
    assert stats.median_matches_per_session == 3
    # выиграл партии: 11-7=4, 11-9=2, 11-9=2 → медиана 2
    assert stats.median_point_diff == 2
    # все партии 5 минут
    assert stats.median_match_duration_s == 300.0


def test_player_stats_aggregate_session_does_not_contribute_gaps():
    user = 1001
    other = 2002
    t = datetime(2026, 5, 10, 18, 0)
    agg = TennisSession(
        id=1,
        chat_id=-100,
        player_a_id=user,
        player_b_id=other,
        started_at=t,
        ended_at=t,
        is_aggregate_only=True,
        matches=aggregate_session_matches(t, 5, 3),
    )
    stats = player_stats([agg], user)
    assert stats.wins == 5
    assert stats.losses == 3
    assert stats.median_gap_s is None
    assert stats.median_point_diff is None  # счета не записаны
    assert stats.median_match_duration_s == 0.0  # длительность 0


def test_player_stats_longest_win_streak():
    user = 1001
    other = 2002
    t = datetime(2026, 5, 10, 18, 0)
    matches = [
        TennisMatch(started_at=t, winner=SIDE_A),                # win
        TennisMatch(started_at=t, winner=SIDE_A),                # win
        TennisMatch(started_at=t, winner=SIDE_B),                # loss
        TennisMatch(started_at=t, winner=SIDE_A),                # win
        TennisMatch(started_at=t, winner=SIDE_A),                # win
        TennisMatch(started_at=t, winner=SIDE_A),                # win — streak 3
        TennisMatch(started_at=t, winner=SIDE_B),                # loss
    ]
    s = TennisSession(
        id=1, chat_id=-100,
        player_a_id=user, player_b_id=other,
        started_at=t, matches=matches,
    )
    stats = player_stats([s], user)
    assert stats.longest_win_streak == 3


def test_player_stats_empty_input():
    stats = player_stats([], 1001)
    assert stats.sessions == 0
    assert stats.matches == 0
    assert stats.win_rate == 0.0
    assert stats.median_matches_per_session is None
    assert stats.longest_win_streak == 0


# ── bulk import parser ────────────────────────────────────────────────────────

from steward.features.tennis import _parse_bulk_history, _parse_score_pair


def test_parse_score_pair_various_separators():
    assert _parse_score_pair("11:7") == (11, 7)
    assert _parse_score_pair("11-7") == (11, 7)
    assert _parse_score_pair("11 7") == (11, 7)
    assert _parse_score_pair("  11   :  7 ") == (11, 7)


def test_parse_score_pair_rejects_bad_input():
    with pytest.raises(ValueError):
        _parse_score_pair("11")
    with pytest.raises(ValueError):
        _parse_score_pair("11:7:5")


def test_parse_bulk_mixed_aggregate_and_detailed():
    text = """
2024-05-10 @ivan 5:3
2024-05-12 @ivan 7:2

2024-05-15 @ivan
11:7
11:9
9:11
12:10

2024-05-20 @ivan 4:6
2024-05-22 @ivan
11:5
9:11
11:8
2024-05-25 @ivan 3:4
"""
    entries = _parse_bulk_history(text)
    assert len(entries) == 6

    assert entries[0].mode == "aggregate"
    assert (entries[0].wins_a, entries[0].wins_b) == (5, 3)
    assert entries[0].date == datetime(2024, 5, 10)
    assert entries[0].opponent_raw == "@ivan"

    assert entries[2].mode == "detailed"
    assert entries[2].score_pairs == [(11, 7), (11, 9), (9, 11), (12, 10)]

    assert entries[4].mode == "detailed"
    assert entries[4].score_pairs == [(11, 5), (9, 11), (11, 8)]

    assert entries[5].mode == "aggregate"
    assert (entries[5].wins_a, entries[5].wins_b) == (3, 4)


def test_parse_bulk_rejects_party_without_date():
    with pytest.raises(ValueError, match="без даты"):
        _parse_bulk_history("11:7")


def test_parse_bulk_rejects_party_after_aggregate():
    # агрегатная строка финализируется сразу — следующая «11:7» уже «без даты»
    with pytest.raises(ValueError, match="без даты"):
        _parse_bulk_history("2024-05-10 @ivan 5:3\n11:7")


def test_parse_bulk_rejects_detailed_without_matches():
    with pytest.raises(ValueError, match="без партий"):
        _parse_bulk_history("2024-05-10 @ivan\n2024-05-12 @ivan 5:3")


def test_parse_bulk_rejects_invalid_party_score():
    with pytest.raises(ValueError, match="не похоже на партию"):
        _parse_bulk_history("2024-05-10 @ivan\n11:10")  # deuce не разошёлся


def test_parse_bulk_rejects_bad_date():
    with pytest.raises(ValueError, match="не понимаю дату"):
        _parse_bulk_history("2024-13-10 @ivan 5:3")


def test_parse_bulk_empty_input():
    with pytest.raises(ValueError, match="Пустой"):
        _parse_bulk_history("")
    with pytest.raises(ValueError, match="Пустой"):
        _parse_bulk_history("   \n  \n")


def test_parse_bulk_supports_dash_and_x_separators():
    text = "2024-05-10 @ivan 5-3\n2024-05-11 @ivan 7x2"
    entries = _parse_bulk_history(text)
    assert (entries[0].wins_a, entries[0].wins_b) == (5, 3)
    assert (entries[1].wins_a, entries[1].wins_b) == (7, 2)


def test_parse_bulk_supports_id_as_opponent():
    text = "2024-05-10 123456 5:3"
    entries = _parse_bulk_history(text)
    assert entries[0].opponent_raw == "123456"
