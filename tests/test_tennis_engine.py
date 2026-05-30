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

from steward.tennis.import_parser import (
    parse_bulk_history as _parse_bulk_history,
    parse_score_pair as _parse_score_pair,
)


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


# ── TennisRoom integration: запись партий счётом + undo ──────────────────────

import asyncio

from steward.tennis.room_manager import TennisRoom


class _FakeRepository:
    async def save(self):
        pass


class _FakeManager:
    async def _announce_match(self, *args, **kwargs):
        pass

    async def _announce_set_end(self, *args, **kwargs):
        pass


def _live_session(**overrides) -> TennisSession:
    base = TennisSession(
        id=1,
        chat_id=-100,
        player_a_id=1001,
        player_b_id=2002,
        started_at=datetime(2026, 5, 14, 18, 0),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _make_room(session: TennisSession) -> TennisRoom:
    return TennisRoom(session, _FakeRepository(), _FakeManager())


def _run(coro):
    return asyncio.run(coro)


def test_record_match_with_score_completes_and_rotates():
    s = _live_session(first_server="a", serve_streak=1)
    room = _make_room(s)
    ok, _err, info = _run(room.record_match_with_score(11, 7))
    assert ok and info["match_completed"]
    assert len(s.matches) == 1
    assert s.matches[0].winner == "a"
    assert s.matches[0].score_a == 11 and s.matches[0].score_b == 7
    assert s.first_server == "b"


def test_record_match_with_score_rejects_bad_score():
    s = _live_session()
    room = _make_room(s)
    ok, _err, _ = _run(room.record_match_with_score(11, 10))  # deuce не разошёлся
    assert not ok
    assert len(s.matches) == 0


def test_serve_streak_rotates_every_n_partii():
    # serve_streak=2: 1-я и 2-я партии — first=a; 3-я и 4-я — first=b
    s = _live_session(first_server="a", serve_streak=2)
    room = _make_room(s)
    _run(room.record_match_with_score(11, 7))  # партия 1 — пока не переходим
    assert s.first_server == "a"
    _run(room.record_match_with_score(11, 7))  # партия 2 — переход
    assert s.first_server == "b"
    _run(room.record_match_with_score(11, 7))  # партия 3 — не переходим
    assert s.first_server == "b"
    _run(room.record_match_with_score(11, 7))  # партия 4 — переход
    assert s.first_server == "a"


def test_serve_streak_one_means_alternate_every_party():
    s = _live_session(first_server="a", serve_streak=1)
    room = _make_room(s)
    _run(room.record_match_with_score(11, 7))
    assert s.first_server == "b"
    _run(room.record_match_with_score(11, 7))
    assert s.first_server == "a"


def test_undo_revives_first_server_on_streak_boundary():
    s = _live_session(first_server="a", serve_streak=2)
    room = _make_room(s)
    _run(room.record_match_with_score(11, 7))   # 1: first=a (нет перехода)
    _run(room.record_match_with_score(11, 7))   # 2: first=b (был переход)
    assert s.first_server == "b"
    _run(room.undo_last_match())                # откатываем 2-ю — переход тоже откатывается
    assert s.first_server == "a"
    assert len(s.matches) == 1


def test_undo_last_match_rolls_back_one_party():
    s = _live_session(first_server="a", serve_streak=1)
    room = _make_room(s)
    _run(room.record_match_with_score(11, 7))
    assert s.first_server == "b"
    ok, _err = _run(room.undo_last_match())
    assert ok
    assert len(s.matches) == 0
    assert s.first_server == "a"


def test_undo_last_match_empty_returns_false():
    s = _live_session()
    room = _make_room(s)
    ok, err = _run(room.undo_last_match())
    assert not ok
    assert "Нечего" in err


def test_update_match_changes_score_and_winner():
    s = _live_session()
    room = _make_room(s)
    _run(room.record_match_with_score(11, 7))
    assert s.matches[0].winner == "a"
    ok, _err = _run(room.update_match(0, 9, 11))
    assert ok
    assert s.matches[0].score_a == 9 and s.matches[0].score_b == 11
    assert s.matches[0].winner == "b"


def test_update_match_rejects_bad_score():
    s = _live_session()
    room = _make_room(s)
    _run(room.record_match_with_score(11, 7))
    ok, _err = _run(room.update_match(0, 11, 10))  # deuce не разошёлся
    assert not ok
    assert s.matches[0].score_a == 11 and s.matches[0].score_b == 7


def test_update_match_after_session_closed_within_window():
    s = _live_session()
    s.ended_at = datetime(2026, 5, 14, 19, 0)  # та же дата что started_at + 1ч
    # эмулируем «недавнее закрытие»: ended_at = now почти
    from datetime import datetime as _dt
    s.ended_at = _dt.now()
    room = _make_room(s)
    s.matches.append(TennisMatch(started_at=s.started_at, ended_at=s.started_at,
                                  winner="a", score_a=11, score_b=7))
    ok, _err = _run(room.update_match(0, 11, 9))
    assert ok and s.matches[0].score_b == 9


def test_update_match_after_edit_window_rejected():
    s = _live_session()
    s.ended_at = datetime(2025, 1, 1, 12, 0)  # давно
    s.matches.append(TennisMatch(started_at=s.started_at, ended_at=s.started_at,
                                  winner="a", score_a=11, score_b=7))
    room = _make_room(s)
    ok, err = _run(room.update_match(0, 11, 9))
    assert not ok
    assert "Окно" in err


# ── sport helpers: next_first_server / normalize_sport / sport_meta ───────────

from steward.tennis.engine import (
    DEFAULT_SPORT,
    SPORT_SQUASH,
    SPORT_TABLE_TENNIS,
    next_first_server,
    normalize_sport,
    sport_meta,
)


def test_normalize_sport_falls_back_to_default():
    assert normalize_sport(None) == DEFAULT_SPORT
    assert normalize_sport("") == DEFAULT_SPORT
    assert normalize_sport("badminton") == DEFAULT_SPORT
    assert normalize_sport(SPORT_SQUASH) == SPORT_SQUASH
    assert normalize_sport(SPORT_TABLE_TENNIS) == SPORT_TABLE_TENNIS


def test_sport_meta_has_required_keys():
    for sport in (SPORT_TABLE_TENNIS, SPORT_SQUASH):
        meta = sport_meta(sport)
        assert {"label", "label_short", "genitive", "emoji"} <= meta.keys()
    # неизвестный спорт → мета дефолтного
    assert sport_meta("nope") == sport_meta(DEFAULT_SPORT)


def _match(winner: str) -> TennisMatch:
    t = datetime(2026, 5, 14, 18, 0)
    return TennisMatch(started_at=t, ended_at=t, winner=winner, score_a=11, score_b=7)


def test_next_first_server_table_tennis_streak_2():
    # initial=a, каждые 2 партии переход
    def srv(n_matches):
        ms = [_match("a")] * n_matches
        return next_first_server(SPORT_TABLE_TENNIS, ms, initial_server="a", serve_streak=2)
    assert srv(0) == "a"
    assert srv(1) == "a"
    assert srv(2) == "b"
    assert srv(3) == "b"
    assert srv(4) == "a"


def test_next_first_server_table_tennis_streak_1_alternates():
    def srv(n_matches):
        ms = [_match("a")] * n_matches
        return next_first_server(SPORT_TABLE_TENNIS, ms, initial_server="a", serve_streak=1)
    assert srv(0) == "a"
    assert srv(1) == "b"
    assert srv(2) == "a"


def test_next_first_server_table_tennis_respects_initial_b():
    ms = [_match("a")] * 2
    assert next_first_server(SPORT_TABLE_TENNIS, ms, initial_server="b", serve_streak=2) == "a"
    assert next_first_server(SPORT_TABLE_TENNIS, [], initial_server="b", serve_streak=2) == "b"


def test_next_first_server_squash_winner_serves():
    # В сквоше следующую партию подаёт победитель предыдущей.
    assert next_first_server(SPORT_SQUASH, [], initial_server="a", serve_streak=2) == "a"
    assert next_first_server(SPORT_SQUASH, [], initial_server="b", serve_streak=2) == "b"
    assert next_first_server(SPORT_SQUASH, [_match("a")], initial_server="a", serve_streak=2) == "a"
    assert next_first_server(SPORT_SQUASH, [_match("b")], initial_server="a", serve_streak=2) == "b"
    assert next_first_server(SPORT_SQUASH, [_match("a"), _match("b")], initial_server="a", serve_streak=2) == "b"


# ── TennisRoom: squash serve rules ────────────────────────────────────────────

def test_squash_room_winner_serves_next_party():
    s = _live_session(sport=SPORT_SQUASH, first_server="a", initial_server="a", serve_streak=2)
    room = _make_room(s)
    _run(room.record_match_with_score(11, 7))   # выиграл a → a подаёт
    assert s.first_server == "a"
    _run(room.record_match_with_score(7, 11))   # выиграл b → b подаёт
    assert s.first_server == "b"
    _run(room.record_match_with_score(7, 11))   # снова b
    assert s.first_server == "b"


def test_squash_room_undo_recomputes_server():
    s = _live_session(sport=SPORT_SQUASH, first_server="a", initial_server="a", serve_streak=2)
    room = _make_room(s)
    _run(room.record_match_with_score(11, 7))   # a
    _run(room.record_match_with_score(7, 11))   # b
    assert s.first_server == "b"
    _run(room.undo_last_match())                # откат к [a-win] → снова a подаёт
    assert s.first_server == "a"
    assert len(s.matches) == 1


def test_squash_uses_same_party_validation():
    # Счёт партии у сквоша тот же (PAR 11, разница ≥2).
    s = _live_session(sport=SPORT_SQUASH)
    room = _make_room(s)
    ok, _err, _ = _run(room.record_match_with_score(11, 10))  # deuce не разошёлся
    assert not ok
    assert len(s.matches) == 0


# ── player_stats: sport filtering ─────────────────────────────────────────────

def test_player_stats_filters_by_sport():
    user = 1001
    other = 2002
    tt = _build_detailed_session(1, user, other, [(11, 7), (11, 9)], datetime(2026, 5, 10, 18, 0))
    tt.sport = SPORT_TABLE_TENNIS
    sq = _build_detailed_session(2, user, other, [(8, 11), (11, 5), (11, 6)], datetime(2026, 5, 11, 18, 0))
    sq.sport = SPORT_SQUASH

    all_stats = player_stats([tt, sq], user)
    assert all_stats.matches == 5

    tt_stats = player_stats([tt, sq], user, sport=SPORT_TABLE_TENNIS)
    assert tt_stats.sessions == 1
    assert tt_stats.matches == 2
    assert tt_stats.wins == 2

    sq_stats = player_stats([tt, sq], user, sport=SPORT_SQUASH)
    assert sq_stats.sessions == 1
    assert sq_stats.matches == 3
    assert sq_stats.wins == 2


def test_player_stats_legacy_sessions_count_as_table_tennis():
    # Старые сессии без поля sport (дефолт table_tennis) учитываются в фильтре теннис.
    user = 1001
    other = 2002
    legacy = _build_detailed_session(1, user, other, [(11, 7)], datetime(2026, 5, 10, 18, 0))
    # не трогаем legacy.sport — остаётся дефолт "table_tennis"
    assert player_stats([legacy], user, sport=SPORT_TABLE_TENNIS).matches == 1
    assert player_stats([legacy], user, sport=SPORT_SQUASH).matches == 0


# ── point-by-point: pure helpers ──────────────────────────────────────────────

from steward.tennis.engine import (
    current_point_server,
    is_party_complete,
    party_point_to_side,
)


@pytest.mark.parametrize(
    "a,b,done",
    [
        (0, 0, False),
        (11, 0, True),
        (11, 9, True),
        (11, 10, False),   # deuce
        (12, 10, True),
        (12, 11, False),
        (13, 11, True),
        (10, 9, False),
    ],
)
def test_is_party_complete(a, b, done):
    assert is_party_complete(a, b) is done


def test_party_point_to_side_counts_log():
    assert party_point_to_side([]) == (0, 0)
    assert party_point_to_side(["a", "a", "b"]) == (2, 1)
    assert party_point_to_side(["b", "b", "b", "a"]) == (1, 3)


def test_current_point_server_table_tennis_every_two_points():
    # initial server a: подача переходит каждые 2 очка
    srv = lambda a, b: current_point_server(SPORT_TABLE_TENNIS, a, b, party_first_server="a")
    assert srv(0, 0) == "a"
    assert srv(1, 0) == "a"
    assert srv(1, 1) == "b"   # 2 очка разыграно → переход
    assert srv(2, 1) == "b"
    assert srv(2, 2) == "a"   # 4 очка → снова a


def test_current_point_server_table_tennis_deuce_alternates_each_point():
    srv = lambda a, b: current_point_server(SPORT_TABLE_TENNIS, a, b, party_first_server="a")
    # при 10:10 — каждое очко меняет подающего
    s1 = srv(10, 10)
    s2 = srv(11, 10)
    assert s1 != s2


def test_current_point_server_squash_winner_serves():
    srv = lambda a, b: current_point_server(SPORT_SQUASH, a, b, party_first_server="a")
    assert srv(0, 0) == "a"
    assert srv(3, 1) == "a"   # a ведёт → a подаёт
    assert srv(1, 3) == "b"


# ── point-by-point: TennisRoom ────────────────────────────────────────────────

def test_add_point_accumulates_without_finalizing():
    s = _live_session(first_server="a", initial_server="a")
    room = _make_room(s)
    _run(room.add_point("a"))
    _run(room.add_point("b"))
    _run(room.add_point("a"))
    assert s.current_score_a == 2 and s.current_score_b == 1
    assert s.points_log == ["a", "b", "a"]
    assert len(s.matches) == 0


def test_add_point_finalizes_party_on_11():
    s = _live_session(first_server="a", initial_server="a", serve_streak=1)
    room = _make_room(s)
    for _ in range(11):
        ok, _err, info = _run(room.add_point("a"))
    assert ok and info["match_completed"]
    assert len(s.matches) == 1
    assert s.matches[0].score_a == 11 and s.matches[0].score_b == 0
    assert s.matches[0].winner == "a"
    # лайв-счёт обнулён под следующую партию
    assert s.current_score_a == 0 and s.current_score_b == 0
    assert s.points_log == []
    # подача переключилась по serve_streak=1
    assert s.first_server == "b"


def test_add_point_deuce_requires_two_point_gap():
    s = _live_session(first_server="a", initial_server="a")
    room = _make_room(s)
    for _ in range(10):
        _run(room.add_point("a"))
    for _ in range(10):
        _run(room.add_point("b"))
    # 10:10 — партия не закончена
    assert len(s.matches) == 0
    _run(room.add_point("a"))  # 11:10 — ещё нет
    assert len(s.matches) == 0
    _run(room.add_point("a"))  # 12:10 — победа
    assert len(s.matches) == 1
    assert s.matches[0].score_a == 12 and s.matches[0].score_b == 10


def test_undo_point_removes_last_point():
    s = _live_session()
    room = _make_room(s)
    _run(room.add_point("a"))
    _run(room.add_point("b"))
    ok, _err = _run(room.undo_point())
    assert ok
    assert s.points_log == ["a"]
    assert s.current_score_a == 1 and s.current_score_b == 0


def test_undo_point_empty_returns_false():
    s = _live_session()
    room = _make_room(s)
    ok, err = _run(room.undo_point())
    assert not ok
    assert "нет очков" in err.lower()


def test_reset_current_party_clears_points():
    s = _live_session()
    room = _make_room(s)
    _run(room.add_point("a"))
    _run(room.add_point("a"))
    ok, _err = _run(room.reset_current_party())
    assert ok
    assert s.points_log == []
    assert s.current_score_a == 0 and s.current_score_b == 0


def test_record_match_with_score_clears_pending_points():
    # Если велась point-by-point партия, ручная запись готового счёта её перебивает.
    s = _live_session()
    room = _make_room(s)
    _run(room.add_point("a"))
    _run(room.add_point("a"))
    _run(room.record_match_with_score(11, 5))
    assert len(s.matches) == 1
    assert s.current_score_a == 0 and s.current_score_b == 0
    assert s.points_log == []
