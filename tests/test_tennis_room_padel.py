"""Интеграция падела в room_manager: point-by-point финализация матча по сетам."""
import asyncio
from datetime import datetime

from steward.data.models.tennis import TennisSession
from steward.tennis.room_manager import TennisRoomManager
from tests.conftest import make_repository


def _padel_session(repo, *, sets_to_win=1, golden=True):
    s = TennisSession(
        id=1,
        chat_id=-100,
        sport="padel",
        player_a_id=1,
        player_b_id=2,
        player_a2_id=3,
        player_b2_id=4,
        started_at=datetime.now(),
        last_activity_at=datetime.now(),
        initiator_id=1,
        golden_point=golden,
        sets_to_win=sets_to_win,
    )
    repo.db.tennis_sessions.append(s)
    return s


def _room(repo, session):
    mgr = TennisRoomManager()
    return mgr.attach(session, repo)


async def test_padel_point_by_point_finalizes_match_by_sets():
    repo = make_repository()
    s = _padel_session(repo, sets_to_win=1)
    room = _room(repo, s)
    # сет 6:0 = 24 очка a при «золотом мяче» (4 очка на гейм)
    info = None
    for _ in range(24):
        ok, err, info = await room.add_point("a")
        assert ok, err
    await asyncio.sleep(0.01)   # дать отработать announce-таску
    assert info["match_completed"] is True
    assert info["winner"] == "a"
    assert len(s.matches) == 1
    assert (s.matches[0].score_a, s.matches[0].score_b) == (1, 0)
    assert s.points_log == []   # journal сброшен под следующий матч


async def test_padel_match_not_complete_after_one_set_when_best_of_three():
    repo = make_repository()
    s = _padel_session(repo, sets_to_win=2)
    room = _room(repo, s)
    for _ in range(24):
        ok, _err, info = await room.add_point("a")
        assert ok
    # один сет взят, но матч (best-of-3) ещё идёт — TennisMatch не пишется
    assert info["match_completed"] is False
    assert s.matches == []
    st = room.to_state(1)
    assert st["padel"]["sets"] == [1, 0]


async def test_padel_to_state_has_padel_block():
    repo = make_repository()
    s = _padel_session(repo, sets_to_win=2)
    room = _room(repo, s)
    await room.add_point("a")   # 15:0
    st = room.to_state(1)
    assert st["sport"] == "padel"
    assert st["padel"] is not None
    assert st["padel"]["points"] == ["15", "0"]
    assert st["padel"]["sets"] == [0, 0]
    assert st["current_score"] == [0, 0]   # для падела current_score — это сеты


async def test_padel_undo_point_reverts_state():
    repo = make_repository()
    s = _padel_session(repo, sets_to_win=2)
    room = _room(repo, s)
    await room.add_point("a")
    await room.add_point("a")   # 30:0
    ok, err = await room.undo_point()
    assert ok, err
    st = room.to_state(1)
    assert st["padel"]["points"] == ["15", "0"]


async def test_padel_rejects_manual_score_entry():
    repo = make_repository()
    s = _padel_session(repo)
    room = _room(repo, s)
    ok, err, _info = await room.record_match_with_score(6, 0)
    assert not ok
    assert "падел" in err.lower()


async def test_padel_rejects_match_edit():
    repo = make_repository()
    s = _padel_session(repo, sets_to_win=1)
    room = _room(repo, s)
    for _ in range(24):
        await room.add_point("a")
    ok, err = await room.update_match(0, 2, 1)
    assert not ok
