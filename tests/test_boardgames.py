import asyncio

import chess

from steward.boardgames import checkers_logic as cl
from steward.boardgames import room_manager as rm


def _empty():
    return [["." for _ in range(8)] for _ in range(8)]


# ---- Шашки: форс максимального взятия ----

def test_checkers_forces_maximum_capture():
    b = _empty()
    b[5][5] = "w"
    b[4][4] = "b"  # начало цепочки из двух взятий
    b[2][2] = "b"  # продолжение цепочки
    b[4][6] = "b"  # альтернативное одиночное взятие
    moves = cl.legal_moves(b, "white")
    assert moves and all(m["captures"] for m in moves)
    # короткое взятие (->(3,7)) запрещено, остаётся только длинная серия
    assert {tuple(m["to"]) for m in moves} == {(3, 3)}
    assert all(m["from"] == [5, 5] for m in moves)


def test_checkers_forced_continuation():
    b = _empty()
    b[5][5] = "w"
    b[4][4] = "b"
    b[2][2] = "b"
    first = cl.legal_moves(b, "white")[0]
    nb, _ = cl.apply_move(b, first)
    cont = cl.legal_moves(nb, "white", first["to"])
    assert {tuple(m["to"]) for m in cont} == {(1, 1)}
    assert cont[0]["captures"] == [[2, 2]]


def test_checkers_promotion_during_capture_makes_king():
    b = _empty()
    b[2][2] = "w"
    b[1][1] = "b"  # взятие с приземлением на (0,0) -> превращение
    mv = cl.legal_moves(b, "white")[0]
    nb, piece = cl.apply_move(b, mv)
    assert mv["to"] == [0, 0]
    assert piece == "W"
    assert nb[0][0] == "W"


def test_checkers_simple_moves_when_no_capture():
    b = _empty()
    b[5][2] = "w"
    moves = cl.legal_moves(b, "white")
    assert moves and all(not m["captures"] for m in moves)
    assert {tuple(m["to"]) for m in moves} == {(4, 1), (4, 3)}


# ---- Шахматы: пат vs мат против бота ----

def _bot_chess_room(fen, bot_side):
    room = rm.BoardRoom("t", "t", rm.GAME_CHESS, 1, "p", 0, bot_side, "easy")
    room.chess_board = chess.Board(fen)
    room.checkers_board = None
    room.started = True
    room.finished = False
    room.turn = bot_side
    return room


def test_bot_stalemate_is_draw(monkeypatch):
    monkeypatch.setattr(rm, "BOT_MOVE_DELAY", (0, 0))
    room = _bot_chess_room("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "black")
    asyncio.run(rm._maybe_bot_move(room))
    assert room.finished
    assert room.winner == "draw"


def test_bot_checkmate_is_loss(monkeypatch):
    monkeypatch.setattr(rm, "BOT_MOVE_DELAY", (0, 0))
    room = _bot_chess_room("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", "black")
    asyncio.run(rm._maybe_bot_move(room))
    assert room.finished
    assert room.winner == "white"
