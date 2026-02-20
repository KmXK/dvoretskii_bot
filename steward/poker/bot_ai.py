import random
from steward.poker.engine import PokerGame, best_hand

BOT_NAMES = [
    "Добрыня", "Иннокентий", "Святослав", "Любава", "Ярослав",
    "Забава", "Всеволод", "Млада", "Ратибор", "Василиса",
    "Мирослав", "Лада", "Богдан", "Снежана", "Ермолай",
]

DIFFICULTY_EASY = "easy"
DIFFICULTY_MEDIUM = "medium"
DIFFICULTY_HARD = "hard"
DIFFICULTIES = [DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD]


def _hand_strength(hole_cards, community):
    if not hole_cards:
        return 0, 0
    score, _ = best_hand(hole_cards, community)
    return score[0], score


def _preflop_score(hole_cards):
    if len(hole_cards) < 2:
        return 0
    r1, r2 = hole_cards[0].rank, hole_cards[1].rank
    suited = hole_cards[0].suit == hole_cards[1].suit

    high = max(r1, r2)
    low = min(r1, r2)

    if r1 == r2:
        return min(r1 * 6, 100)

    score = high * 2 + low
    if suited:
        score += 4
    if high - low <= 2:
        score += 3
    if high >= 14:
        score += 8
    elif high >= 13:
        score += 5
    elif high >= 12:
        score += 3
    return score


def _decide_easy(game: PokerGame, player_idx: int) -> tuple[str, int]:
    p = game.players[player_idx]
    community = game.community
    hole = p.hole_cards
    current_bet = game.current_bet
    to_call = max(0, current_bet - p.bet)
    bb = game.big_blind

    can_check = to_call == 0
    can_call = 0 < to_call < p.chips

    if can_check:
        if random.random() < 0.15:
            raise_to = current_bet + bb * 2
            raise_to = min(raise_to, p.chips + p.bet)
            if p.chips > to_call:
                return "raise", raise_to
        return "check", 0

    if to_call <= bb * 2:
        if random.random() < 0.7:
            if can_call:
                return "call", 0
            return "all_in", 0
        return "fold", 0

    if to_call <= bb * 5:
        if random.random() < 0.4:
            if can_call:
                return "call", 0
            return "all_in", 0
        return "fold", 0

    if community:
        rank, _ = _hand_strength(hole, community)
        if rank >= 2 and random.random() < 0.6:
            if can_call:
                return "call", 0
            return "all_in", 0

    if random.random() < 0.15:
        if can_call:
            return "call", 0
        return "all_in", 0

    return "fold", 0


def _decide_medium(game: PokerGame, player_idx: int) -> tuple[str, int]:
    p = game.players[player_idx]
    community = game.community
    hole = p.hole_cards
    pot = game.pot
    current_bet = game.current_bet
    to_call = max(0, current_bet - p.bet)
    bb = game.big_blind

    can_check = to_call == 0
    can_call = 0 < to_call < p.chips
    can_raise = p.chips > to_call

    if not community:
        pf = _preflop_score(hole)
        if pf >= 60:
            if can_raise:
                raise_to = current_bet + bb * random.randint(2, 4)
                raise_to = min(raise_to, p.chips + p.bet)
                return "raise", raise_to
            return "all_in", 0
        if pf >= 35:
            if to_call <= bb * 4:
                if can_call:
                    return "call", 0
                if can_check:
                    return "check", 0
                return "all_in", 0
            if can_check:
                return "check", 0
            return "fold", 0
        if pf >= 20:
            if can_check:
                return "check", 0
            if to_call <= bb * 2:
                if can_call:
                    return "call", 0
                return "all_in", 0
            return "fold", 0
        if can_check:
            return "check", 0
        if to_call <= bb and random.random() < 0.3:
            if can_call:
                return "call", 0
            return "all_in", 0
        return "fold", 0

    rank, score = _hand_strength(hole, community)
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0

    if rank >= 5:
        if can_raise:
            raise_to = current_bet + max(bb * 3, pot // 2)
            raise_to = min(raise_to, p.chips + p.bet)
            return "raise", raise_to
        return "all_in", 0

    if rank >= 3:
        if random.random() < 0.6 and can_raise:
            raise_to = current_bet + max(bb * 2, pot // 3)
            raise_to = min(raise_to, p.chips + p.bet)
            return "raise", raise_to
        if can_call:
            return "call", 0
        if can_check:
            return "check", 0
        return "all_in", 0

    if rank >= 1:
        if can_check:
            if random.random() < 0.3 and can_raise:
                raise_to = current_bet + bb * 2
                raise_to = min(raise_to, p.chips + p.bet)
                return "raise", raise_to
            return "check", 0
        if pot_odds < 0.35 and can_call:
            return "call", 0
        if to_call <= bb * 3:
            if can_call:
                return "call", 0
            return "all_in", 0
        return "fold", 0

    if can_check:
        if random.random() < 0.15 and can_raise:
            raise_to = current_bet + bb * 2
            raise_to = min(raise_to, p.chips + p.bet)
            return "raise", raise_to
        return "check", 0

    if to_call <= bb and random.random() < 0.2:
        if can_call:
            return "call", 0

    if random.random() < 0.08 and can_raise:
        raise_to = current_bet + bb * random.randint(2, 4)
        raise_to = min(raise_to, p.chips + p.bet)
        return "raise", raise_to

    return "fold", 0


def _decide_hard(game: PokerGame, player_idx: int) -> tuple[str, int]:
    p = game.players[player_idx]
    community = game.community
    hole = p.hole_cards
    pot = game.pot
    current_bet = game.current_bet
    to_call = max(0, current_bet - p.bet)
    bb = game.big_blind

    can_check = to_call == 0
    can_call = 0 < to_call < p.chips
    can_raise = p.chips > to_call

    active_count = sum(
        1 for pl in game.players
        if not pl.folded and not pl.sitting_out
    )

    if not community:
        pf = _preflop_score(hole)

        if pf >= 65:
            if can_raise:
                raise_to = current_bet + bb * random.randint(3, 5)
                raise_to = min(raise_to, p.chips + p.bet)
                return "raise", raise_to
            return "all_in", 0

        if pf >= 45:
            if to_call <= bb * 3:
                if random.random() < 0.5 and can_raise:
                    raise_to = current_bet + bb * random.randint(2, 3)
                    raise_to = min(raise_to, p.chips + p.bet)
                    return "raise", raise_to
                if can_call:
                    return "call", 0
                if can_check:
                    return "check", 0
                return "all_in", 0
            if to_call <= bb * 6:
                if can_call:
                    return "call", 0
                if can_check:
                    return "check", 0
                return "fold", 0
            if can_check:
                return "check", 0
            return "fold", 0

        if pf >= 30:
            if can_check:
                return "check", 0
            if to_call <= bb * 2 and active_count <= 3:
                if can_call:
                    return "call", 0
                return "all_in", 0
            return "fold", 0

        if can_check:
            if random.random() < 0.12 and can_raise:
                raise_to = current_bet + bb * 3
                raise_to = min(raise_to, p.chips + p.bet)
                return "raise", raise_to
            return "check", 0
        return "fold", 0

    rank, score = _hand_strength(hole, community)
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0

    has_flush_draw = False
    has_straight_draw = False
    if hole and community:
        all_suits = [c.suit for c in hole + community]
        from collections import Counter
        suit_counts = Counter(all_suits)
        has_flush_draw = any(v == 4 for v in suit_counts.values())

        all_ranks = sorted(set(c.rank for c in hole + community))
        for i in range(len(all_ranks) - 3):
            window = all_ranks[i:i + 5] if i + 5 <= len(all_ranks) else all_ranks[i:]
            if len(window) >= 4 and window[-1] - window[0] <= 4:
                has_straight_draw = True
                break

    draw_equity = 0.0
    if has_flush_draw:
        draw_equity += 0.18 if len(community) == 3 else 0.09
    if has_straight_draw:
        draw_equity += 0.16 if len(community) == 3 else 0.08

    if rank >= 6:
        if can_raise:
            if random.random() < 0.3:
                raise_to = current_bet + max(bb * 2, pot // 4)
            else:
                raise_to = current_bet + max(bb * 4, pot)
            raise_to = min(raise_to, p.chips + p.bet)
            return "raise", raise_to
        return "all_in", 0

    if rank >= 4:
        if can_raise:
            raise_to = current_bet + max(bb * 3, int(pot * 0.6))
            raise_to = min(raise_to, p.chips + p.bet)
            return "raise", raise_to
        return "all_in", 0

    if rank >= 3:
        if random.random() < 0.7 and can_raise:
            raise_to = current_bet + max(bb * 2, pot // 3)
            raise_to = min(raise_to, p.chips + p.bet)
            return "raise", raise_to
        if can_call:
            return "call", 0
        if can_check:
            return "check", 0
        return "all_in", 0

    if rank >= 2:
        if can_check:
            if random.random() < 0.4 and can_raise:
                raise_to = current_bet + max(bb * 2, pot // 3)
                raise_to = min(raise_to, p.chips + p.bet)
                return "raise", raise_to
            return "check", 0
        if pot_odds < 0.3 and can_call:
            return "call", 0
        if to_call <= bb * 4:
            if can_call:
                return "call", 0
            return "all_in", 0
        return "fold", 0

    if rank >= 1:
        if can_check:
            if random.random() < 0.25 and can_raise:
                raise_to = current_bet + bb * 2
                raise_to = min(raise_to, p.chips + p.bet)
                return "raise", raise_to
            return "check", 0
        if pot_odds < 0.25 and can_call:
            return "call", 0
        if to_call <= bb * 2:
            if can_call:
                return "call", 0
            return "all_in", 0
        return "fold", 0

    if draw_equity > 0.1:
        if can_check:
            if random.random() < 0.3 and can_raise:
                raise_to = current_bet + max(bb * 2, int(pot * 0.5))
                raise_to = min(raise_to, p.chips + p.bet)
                return "raise", raise_to
            return "check", 0
        if pot_odds < draw_equity + 0.05 and can_call:
            return "call", 0
        if to_call <= bb * 3 and can_call:
            return "call", 0
        return "fold", 0

    if can_check:
        if random.random() < 0.1 and can_raise:
            raise_to = current_bet + max(bb * 3, int(pot * 0.7))
            raise_to = min(raise_to, p.chips + p.bet)
            return "raise", raise_to
        return "check", 0

    if random.random() < 0.06 and can_raise:
        raise_to = current_bet + bb * random.randint(3, 5)
        raise_to = min(raise_to, p.chips + p.bet)
        return "raise", raise_to

    return "fold", 0


def decide(game: PokerGame, player_idx: int, difficulty: str = DIFFICULTY_MEDIUM) -> tuple[str, int]:
    if difficulty == DIFFICULTY_EASY:
        return _decide_easy(game, player_idx)
    elif difficulty == DIFFICULTY_HARD:
        return _decide_hard(game, player_idx)
    return _decide_medium(game, player_idx)
