import random

import chess

BOT_EASY = "easy"
BOT_MEDIUM = "medium"
BOT_HARD = "hard"
BOT_DIFFICULTIES = {BOT_EASY, BOT_MEDIUM, BOT_HARD}

_PIECE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def new_board() -> chess.Board:
    return chess.Board()


def legal_moves(board: chess.Board) -> list[chess.Move]:
    return list(board.legal_moves)


def evaluate_board(board: chess.Board, side: chess.Color) -> int:
    score = 0
    for ptype, val in _PIECE_VALUE.items():
        score += len(board.pieces(ptype, side)) * val
        score -= len(board.pieces(ptype, not side)) * val
    if board.is_check():
        score += 30 if board.turn != side else -30
    return score


def _move_tactical_bonus(board: chess.Board, mv: chess.Move) -> int:
    bonus = 0
    if board.is_capture(mv):
        captured = board.piece_at(mv.to_square)
        if captured is not None:
            bonus += _PIECE_VALUE.get(captured.piece_type, 0) // 3
    if mv.promotion:
        bonus += 200
    return bonus


def choose_bot_move(board: chess.Board, difficulty: str) -> chess.Move | None:
    moves = legal_moves(board)
    if not moves:
        return None

    if difficulty == BOT_EASY:
        return random.choice(moves)

    side = board.turn
    if difficulty == BOT_MEDIUM:
        scored = []
        for mv in moves:
            sc = _move_tactical_bonus(board, mv)
            board.push(mv)
            if board.is_check():
                sc += 50
            board.pop()
            scored.append((sc, mv))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [m for s, m in scored[: max(1, min(4, len(scored)))]]
        return random.choice(top)

    # BOT_HARD: depth=2 alpha-beta negamax + mate constants
    MATE_SCORE = 10**7
    DRAW_SCORE = 0
    SEARCH_DEPTH = 2

    def _terminal_score(b: chess.Board, pov: chess.Color, ply_from_root: int) -> int | None:
        if b.is_checkmate():
            # Side to move is mated.
            if b.turn == pov:
                return -MATE_SCORE + ply_from_root
            return MATE_SCORE - ply_from_root
        if (
            b.is_stalemate()
            or b.is_insufficient_material()
            or b.can_claim_draw()
            or b.is_seventyfive_moves()
            or b.is_fivefold_repetition()
        ):
            return DRAW_SCORE
        return None

    def _negamax(
        b: chess.Board,
        depth: int,
        alpha: int,
        beta: int,
        pov: chess.Color,
        ply_from_root: int,
    ) -> int:
        terminal = _terminal_score(b, pov, ply_from_root)
        if terminal is not None:
            return terminal
        if depth == 0:
            return evaluate_board(b, pov)

        best = -10**9
        ordered = list(b.legal_moves)
        ordered.sort(
            key=lambda m: (
                1 if b.is_capture(m) else 0,
                1 if m.promotion else 0,
            ),
            reverse=True,
        )
        for mv in ordered:
            b.push(mv)
            val = -_negamax(b, depth - 1, -beta, -alpha, pov, ply_from_root + 1)
            b.pop()
            if val > best:
                best = val
            if val > alpha:
                alpha = val
            if alpha >= beta:
                break
        return best

    best_score = -10**9
    best_moves: list[chess.Move] = []
    for mv in moves:
        board.push(mv)
        val = -_negamax(board, SEARCH_DEPTH - 1, -10**9, 10**9, side, 1)
        val += _move_tactical_bonus(board, mv)
        board.pop()
        if val > best_score:
            best_score = val
            best_moves = [mv]
        elif val == best_score:
            best_moves.append(mv)
    return random.choice(best_moves) if best_moves else random.choice(moves)
