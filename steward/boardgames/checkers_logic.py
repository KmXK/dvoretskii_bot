import random

BOT_EASY = "easy"
BOT_MEDIUM = "medium"
BOT_HARD = "hard"


def new_board() -> list[list[str]]:
    board = [["." for _ in range(8)] for _ in range(8)]
    for r in range(3):
        for c in range(8):
            if (r + c) % 2 == 1:
                board[r][c] = "b"
    for r in range(5, 8):
        for c in range(8):
            if (r + c) % 2 == 1:
                board[r][c] = "w"
    return board


def inside(r: int, c: int) -> bool:
    return 0 <= r < 8 and 0 <= c < 8


def piece_side(piece: str) -> str | None:
    if piece in ("w", "W"):
        return "white"
    if piece in ("b", "B"):
        return "black"
    return None


def is_king(piece: str) -> bool:
    return piece in ("W", "B")


def dirs(piece: str) -> list[tuple[int, int]]:
    if piece == "w":
        return [(-1, -1), (-1, 1)]
    if piece == "b":
        return [(1, -1), (1, 1)]
    return [(-1, -1), (-1, 1), (1, -1), (1, 1)]


def captures_from(board: list[list[str]], r: int, c: int, piece: str, side: str) -> list[dict]:
    out: list[dict] = []
    if is_king(piece):
        for dr, dc in dirs(piece):
            rr, cc = r + dr, c + dc
            enemy: list[int] | None = None
            while inside(rr, cc):
                cur = board[rr][cc]
                if cur == ".":
                    if enemy is not None:
                        out.append({"from": [r, c], "to": [rr, cc], "captures": [enemy]})
                    rr += dr
                    cc += dc
                    continue
                if piece_side(cur) == side:
                    break
                if enemy is not None:
                    break
                enemy = [rr, cc]
                rr += dr
                cc += dc
    else:
        for dr, dc in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            r1, c1 = r + dr, c + dc
            r2, c2 = r + 2 * dr, c + 2 * dc
            if not inside(r2, c2):
                continue
            mid = board[r1][c1] if inside(r1, c1) else "."
            if mid == "." or piece_side(mid) == side:
                continue
            if board[r2][c2] != ".":
                continue
            out.append({"from": [r, c], "to": [r2, c2], "captures": [[r1, c1]]})
    return out


def simple_from(board: list[list[str]], r: int, c: int, piece: str) -> list[dict]:
    out: list[dict] = []
    if is_king(piece):
        for dr, dc in dirs(piece):
            rr, cc = r + dr, c + dc
            while inside(rr, cc) and board[rr][cc] == ".":
                out.append({"from": [r, c], "to": [rr, cc], "captures": []})
                rr += dr
                cc += dc
        return out
    piece_dirs = [(-1, -1), (-1, 1)] if piece == "w" else [(1, -1), (1, 1)]
    for dr, dc in piece_dirs:
        rr, cc = r + dr, c + dc
        if inside(rr, cc) and board[rr][cc] == ".":
            out.append({"from": [r, c], "to": [rr, cc], "captures": []})
    return out


def legal_moves(board: list[list[str]], side: str, forced_from: list[int] | None = None) -> list[dict]:
    captures: list[dict] = []
    moves: list[dict] = []
    for r in range(8):
        for c in range(8):
            if forced_from is not None and [r, c] != forced_from:
                continue
            piece = board[r][c]
            if piece_side(piece) != side:
                continue
            captures.extend(captures_from(board, r, c, piece, side))
            if forced_from is None:
                moves.extend(simple_from(board, r, c, piece))
    return captures if captures else moves


def apply_move(board: list[list[str]], mv: dict) -> tuple[list[list[str]], str]:
    b = [row[:] for row in board]
    fr = mv["from"]
    to = mv["to"]
    piece = b[fr[0]][fr[1]]
    b[fr[0]][fr[1]] = "."
    for cr in mv["captures"]:
        b[cr[0]][cr[1]] = "."
    if piece == "w" and to[0] == 0:
        piece = "W"
    if piece == "b" and to[0] == 7:
        piece = "B"
    b[to[0]][to[1]] = piece
    return b, piece


def count_side(board: list[list[str]], side: str) -> int:
    total = 0
    for r in range(8):
        for c in range(8):
            if piece_side(board[r][c]) == side:
                total += 1
    return total


def _eval_board(board: list[list[str]], side: str) -> int:
    score = 0
    for r in range(8):
        for c in range(8):
            p = board[r][c]
            if p == ".":
                continue
            val = 175 if is_king(p) else 100
            s = piece_side(p)
            score += val if s == side else -val
    return score


def choose_bot_move(board: list[list[str]], side: str, forced_from: list[int] | None, difficulty: str) -> dict | None:
    moves = legal_moves(board, side, forced_from)
    if not moves:
        return None
    if difficulty == BOT_EASY:
        return random.choice(moves)
    if difficulty == BOT_MEDIUM:
        captures = [m for m in moves if m["captures"]]
        if captures:
            captures.sort(key=lambda m: len(m["captures"]), reverse=True)
            top = captures[: max(1, min(4, len(captures)))]
            return random.choice(top)
        promo = [m for m in moves if (side == "white" and m["to"][0] == 0) or (side == "black" and m["to"][0] == 7)]
        if promo:
            return random.choice(promo)
        return random.choice(moves)

    # BOT_HARD
    best = -10**9
    best_moves: list[dict] = []
    opp = "black" if side == "white" else "white"
    for mv in moves:
        b2, p2 = apply_move(board, mv)
        cur_forced = None
        if mv["captures"]:
            nxt = captures_from(b2, mv["to"][0], mv["to"][1], p2, side)
            if nxt:
                cur_forced = mv["to"]
        if cur_forced is not None:
            val = _eval_board(b2, side) + 40
        else:
            opp_moves = legal_moves(b2, opp, None)
            if not opp_moves:
                val = 10**7
            else:
                worst = 10**9
                for om in opp_moves:
                    b3, _ = apply_move(b2, om)
                    sc = _eval_board(b3, side)
                    if sc < worst:
                        worst = sc
                val = worst
        if len(mv["captures"]) > 0:
            val += 25 * len(mv["captures"])
        if val > best:
            best = val
            best_moves = [mv]
        elif val == best:
            best_moves.append(mv)
    return random.choice(best_moves) if best_moves else random.choice(moves)
