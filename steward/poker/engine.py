import random
from collections import Counter
from itertools import combinations

SUITS = ["h", "d", "c", "s"]
RANK_SYMBOLS = {
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
    9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A",
}
HAND_NAMES = {
    0: "High Card",
    1: "Pair",
    2: "Two Pair",
    3: "Three of a Kind",
    4: "Straight",
    5: "Flush",
    6: "Full House",
    7: "Four of a Kind",
    8: "Straight Flush",
}


class Card:
    __slots__ = ("rank", "suit")

    def __init__(self, rank: int, suit: str):
        self.rank = rank
        self.suit = suit

    def to_dict(self):
        return {"rank": RANK_SYMBOLS[self.rank], "suit": self.suit}

    def __repr__(self):
        return f"{RANK_SYMBOLS[self.rank]}{self.suit}"


class Deck:
    def __init__(self):
        self.cards = [Card(r, s) for r in range(2, 15) for s in SUITS]
        random.shuffle(self.cards)

    def deal(self, n=1):
        dealt = self.cards[:n]
        self.cards = self.cards[n:]
        return dealt


def _eval5(cards):
    ranks = sorted((c.rank for c in cards), reverse=True)
    suits = [c.suit for c in cards]
    is_flush = len(set(suits)) == 1

    unique = sorted(set(ranks), reverse=True)
    is_straight = False
    high = 0
    if len(unique) == 5:
        if unique[0] - unique[4] == 4:
            is_straight = True
            high = unique[0]
        elif unique == [14, 5, 4, 3, 2]:
            is_straight = True
            high = 5

    counts = Counter(ranks)
    groups = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)

    if is_flush and is_straight:
        return (8, high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if is_flush:
        return (5, *ranks)
    if is_straight:
        return (4, high)
    if groups[0][1] == 3:
        kickers = sorted((g[0] for g in groups[1:]), reverse=True)
        return (3, groups[0][0], *kickers)
    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hp = max(groups[0][0], groups[1][0])
        lp = min(groups[0][0], groups[1][0])
        return (2, hp, lp, groups[2][0])
    if groups[0][1] == 2:
        kickers = sorted((g[0] for g in groups[1:]), reverse=True)
        return (1, groups[0][0], *kickers)
    return (0, *ranks)


def best_hand(hole, community):
    all_cards = hole + community
    if len(all_cards) < 5:
        return (0,), []
    best = None
    best_combo = None
    for combo in combinations(all_cards, 5):
        score = _eval5(list(combo))
        if best is None or score > best:
            best = score
            best_combo = list(combo)
    return best, best_combo


class Player:
    def __init__(self, user_id, name, chips=1000):
        self.user_id = user_id
        self.name = name
        self.chips = chips
        self.hole_cards: list[Card] = []
        self.bet = 0
        self.total_bet = 0
        self.folded = False
        self.all_in = False
        self.acted = False
        self.sitting_out = False

    def reset_hand(self):
        self.hole_cards = []
        self.bet = 0
        self.total_bet = 0
        self.folded = False
        self.all_in = False
        self.acted = False

    def reset_round(self):
        self.bet = 0
        self.acted = False


PHASE_WAITING = "waiting"
PHASE_PREFLOP = "preflop"
PHASE_FLOP = "flop"
PHASE_TURN = "turn"
PHASE_RIVER = "river"
PHASE_SHOWDOWN = "showdown"


class PokerGame:
    def __init__(self, small_blind=10, big_blind=20, start_chips=1000):
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.start_chips = start_chips
        self.players: list[Player] = []
        self.phase = PHASE_WAITING
        self.deck: Deck | None = None
        self.community: list[Card] = []
        self.pot = 0
        self.current_bet = 0
        self.min_raise = big_blind
        self.dealer_idx = -1
        self.current_idx = -1
        self.hand_num = 0
        self.results: dict | None = None
        self.last_action: dict | None = None

    def add_player(self, user_id, name, chips=None):
        if any(p.user_id == user_id for p in self.players):
            return False
        c = chips if chips is not None else self.start_chips
        self.players.append(Player(user_id, name, c))
        return True

    def remove_player(self, user_id):
        idx = next((i for i, p in enumerate(self.players) if p.user_id == user_id), None)
        if idx is None:
            return
        p = self.players[idx]
        if self.phase != PHASE_WAITING:
            p.folded = True
            p.sitting_out = True
            if self.current_idx == idx:
                self._advance()
        else:
            self.players.pop(idx)
            if self.dealer_idx >= len(self.players):
                self.dealer_idx = max(0, len(self.players) - 1)

    def _active(self):
        return [i for i, p in enumerate(self.players) if not p.folded and not p.sitting_out]

    def _can_act(self):
        return [
            i for i, p in enumerate(self.players)
            if not p.folded and not p.all_in and not p.sitting_out and p.chips > 0
        ]

    def _seated_with_chips(self):
        return [i for i, p in enumerate(self.players) if not p.sitting_out and p.chips > 0]

    def _next(self, idx, predicate=None):
        n = len(self.players)
        for off in range(1, n + 1):
            ni = (idx + off) % n
            p = self.players[ni]
            if predicate:
                if predicate(p):
                    return ni
            elif not p.folded and not p.sitting_out:
                return ni
        return -1

    def _post_blind(self, idx, amount):
        p = self.players[idx]
        actual = min(amount, p.chips)
        p.chips -= actual
        p.bet = actual
        p.total_bet = actual
        self.pot += actual
        if p.chips == 0:
            p.all_in = True

    def start_hand(self):
        if len(self._seated_with_chips()) < 2:
            return False

        self.hand_num += 1
        self.deck = Deck()
        self.community = []
        self.pot = 0
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.results = None
        self.last_action = None

        for p in self.players:
            if p.chips <= 0 or p.sitting_out:
                p.folded = True
                p.hole_cards = []
            else:
                p.reset_hand()

        active = self._active()
        if len(active) < 2:
            return False

        not_sitting = lambda p: not p.folded and not p.sitting_out
        if self.hand_num == 1:
            self.dealer_idx = active[0]
        else:
            self.dealer_idx = self._next(self.dealer_idx, not_sitting)

        for i in active:
            self.players[i].hole_cards = self.deck.deal(2)

        if len(active) == 2:
            sb_idx = self.dealer_idx
            bb_idx = self._next(self.dealer_idx)
        else:
            sb_idx = self._next(self.dealer_idx)
            bb_idx = self._next(sb_idx)

        self._post_blind(sb_idx, self.small_blind)
        self._post_blind(bb_idx, self.big_blind)
        self.current_bet = self.big_blind

        can_act_pred = lambda p: not p.folded and not p.all_in and not p.sitting_out and p.chips > 0
        self.current_idx = self._next(bb_idx, can_act_pred)
        if self.current_idx == -1:
            self.phase = PHASE_PREFLOP
            self._run_out()
            return True

        self.phase = PHASE_PREFLOP
        return True

    def action(self, user_id, act, amount=0):
        idx = next((i for i, p in enumerate(self.players) if p.user_id == user_id), None)
        if idx is None:
            return False, "Not in game"
        if idx != self.current_idx:
            return False, "Not your turn"
        if self.phase in (PHASE_WAITING, PHASE_SHOWDOWN):
            return False, "No active hand"

        p = self.players[idx]

        if act == "fold":
            p.folded = True
            p.acted = True
            self.last_action = {"player": idx, "action": "fold"}
            if len(self._active()) <= 1:
                self._finish_single()
                return True, "fold"

        elif act == "check":
            if self.current_bet > p.bet:
                return False, "Cannot check"
            p.acted = True
            self.last_action = {"player": idx, "action": "check"}

        elif act == "call":
            to_call = self.current_bet - p.bet
            if to_call <= 0:
                p.acted = True
                self.last_action = {"player": idx, "action": "check"}
            else:
                actual = min(to_call, p.chips)
                p.chips -= actual
                p.bet += actual
                p.total_bet += actual
                self.pot += actual
                p.acted = True
                if p.chips == 0:
                    p.all_in = True
                self.last_action = {"player": idx, "action": "call", "amount": actual}

        elif act == "raise":
            min_to = self.current_bet + self.min_raise
            if amount < min_to and amount < p.chips + p.bet:
                return False, f"Min raise to {min_to}"

            raise_amount = amount - p.bet
            actual = min(raise_amount, p.chips)
            new_bet = p.bet + actual

            if new_bet > self.current_bet:
                self.min_raise = max(self.min_raise, new_bet - self.current_bet)
                self.current_bet = new_bet
                for i, pl in enumerate(self.players):
                    if i != idx and not pl.folded and not pl.all_in and not pl.sitting_out:
                        pl.acted = False

            p.chips -= actual
            p.bet += actual
            p.total_bet += actual
            self.pot += actual
            p.acted = True
            if p.chips == 0:
                p.all_in = True
            self.last_action = {"player": idx, "action": "raise", "amount": new_bet}

        elif act == "all_in":
            all_in_amount = p.chips
            new_bet = p.bet + all_in_amount

            if new_bet > self.current_bet:
                raise_by = new_bet - self.current_bet
                is_full_raise = raise_by >= self.min_raise
                if is_full_raise:
                    self.min_raise = raise_by
                self.current_bet = new_bet
                if is_full_raise:
                    for i, pl in enumerate(self.players):
                        if i != idx and not pl.folded and not pl.all_in and not pl.sitting_out:
                            pl.acted = False

            p.chips -= all_in_amount
            p.bet += all_in_amount
            p.total_bet += all_in_amount
            self.pot += all_in_amount
            p.all_in = True
            p.acted = True
            self.last_action = {"player": idx, "action": "all_in", "amount": new_bet}

        else:
            return False, "Unknown action"

        self._advance()
        return True, act

    def _advance(self):
        active = self._active()
        if len(active) <= 1:
            self._finish_single()
            return

        can_act = self._can_act()

        round_done = True
        for i in active:
            p = self.players[i]
            if not p.all_in and not p.acted:
                round_done = False
                break
            if not p.all_in and p.bet < self.current_bet:
                round_done = False
                break

        if round_done or len(can_act) == 0:
            self._next_phase()
        else:
            pred = lambda p: not p.folded and not p.all_in and not p.sitting_out and p.chips > 0 and (not p.acted or p.bet < self.current_bet)
            ni = self._next(self.current_idx, pred)
            if ni == -1:
                self._next_phase()
            else:
                self.current_idx = ni

    def _next_phase(self):
        for p in self.players:
            p.reset_round()
        self.current_bet = 0
        self.min_raise = self.big_blind

        can_act = self._can_act()

        if self.phase == PHASE_PREFLOP:
            self.community.extend(self.deck.deal(3))
            self.phase = PHASE_FLOP
        elif self.phase == PHASE_FLOP:
            self.community.extend(self.deck.deal(1))
            self.phase = PHASE_TURN
        elif self.phase == PHASE_TURN:
            self.community.extend(self.deck.deal(1))
            self.phase = PHASE_RIVER
        elif self.phase == PHASE_RIVER:
            self._showdown()
            return

        if len(can_act) <= 1:
            self._next_phase()
            return

        pred = lambda p: not p.folded and not p.all_in and not p.sitting_out and p.chips > 0
        ni = self._next(self.dealer_idx, pred)
        if ni == -1:
            self._next_phase()
        else:
            self.current_idx = ni

    def _run_out(self):
        while self.phase != PHASE_SHOWDOWN:
            self._next_phase()

    def _finish_single(self):
        active = self._active()
        self.phase = PHASE_SHOWDOWN
        if active:
            winner = self.players[active[0]]
            winner.chips += self.pot
            self.results = {
                "winners": [active[0]],
                "pot": self.pot,
                "hands": {},
            }
        self.pot = 0

    def _showdown(self):
        self.phase = PHASE_SHOWDOWN
        active = self._active()

        if len(active) <= 1:
            self._finish_single()
            return

        evals = {}
        for i in active:
            p = self.players[i]
            score, combo = best_hand(p.hole_cards, self.community)
            evals[i] = (score, combo)

        bet_levels = sorted(set(self.players[i].total_bet for i in active))
        pots = []
        prev = 0
        for level in bet_levels:
            if level <= prev:
                continue
            pot_amount = 0
            for p in self.players:
                contrib = min(p.total_bet, level) - min(p.total_bet, prev)
                pot_amount += contrib
            eligible = [i for i in active if self.players[i].total_bet >= level]
            if pot_amount > 0 and eligible:
                pots.append((pot_amount, eligible))
            prev = level

        all_winners = set()
        total_won = {}
        for pot_amount, eligible in pots:
            best_score = max(evals[i][0] for i in eligible)
            winners = [i for i in eligible if evals[i][0] == best_score]
            share = pot_amount // len(winners)
            remainder = pot_amount % len(winners)
            for j, w in enumerate(winners):
                won = share + (1 if j < remainder else 0)
                self.players[w].chips += won
                total_won[w] = total_won.get(w, 0) + won
                all_winners.add(w)

        self.results = {
            "winners": list(all_winners),
            "pot": sum(pa for pa, _ in pots),
            "hands": {
                i: {
                    "score": evals[i][0][0],
                    "name": HAND_NAMES.get(evals[i][0][0], ""),
                    "cards": [c.to_dict() for c in evals[i][1]],
                    "won": total_won.get(i, 0),
                }
                for i in active
            },
        }
        self.pot = 0

    def state_for(self, user_id):
        idx = next((i for i, p in enumerate(self.players) if p.user_id == user_id), -1)

        players_data = []
        for i, p in enumerate(self.players):
            pd = {
                "id": p.user_id,
                "name": p.name,
                "chips": p.chips,
                "bet": p.bet,
                "totalBet": p.total_bet,
                "folded": p.folded,
                "allIn": p.all_in,
                "sittingOut": p.sitting_out,
                "cards": None,
            }
            if self.phase == PHASE_SHOWDOWN and not p.folded and p.hole_cards:
                pd["cards"] = [c.to_dict() for c in p.hole_cards]
            players_data.append(pd)

        me = self.players[idx] if idx >= 0 else None

        actions = []
        if me and idx == self.current_idx and self.phase not in (PHASE_WAITING, PHASE_SHOWDOWN):
            call_needed = max(0, self.current_bet - me.bet)
            actions.append("fold")
            if call_needed <= 0:
                actions.append("check")
            elif call_needed >= me.chips:
                pass
            else:
                actions.append("call")
            if me.chips > 0:
                if call_needed < me.chips:
                    actions.append("raise")
                actions.append("all_in")

        call_amount = max(0, self.current_bet - me.bet) if me else 0
        min_raise_to = self.current_bet + self.min_raise

        return {
            "phase": self.phase,
            "community": [c.to_dict() for c in self.community],
            "pot": self.pot,
            "currentBet": self.current_bet,
            "dealerIndex": self.dealer_idx,
            "currentIndex": self.current_idx if self.phase not in (PHASE_WAITING, PHASE_SHOWDOWN) else -1,
            "myIndex": idx,
            "myCards": [c.to_dict() for c in me.hole_cards] if me and me.hole_cards else [],
            "players": players_data,
            "minRaise": self.min_raise,
            "minRaiseTo": min_raise_to,
            "callAmount": call_amount,
            "handNum": self.hand_num,
            "actions": actions,
            "results": self.results,
            "lastAction": self.last_action,
            "smallBlind": self.small_blind,
            "bigBlind": self.big_blind,
        }
