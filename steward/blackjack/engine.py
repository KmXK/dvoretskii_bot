import random

SUITS = ["h", "d", "c", "s"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

PHASE_WAITING = "waiting"
PHASE_PLAYING = "playing"
PHASE_SHOWDOWN = "showdown"


def _card_value(rank: str) -> int:
    if rank == "A":
        return 11
    if rank in {"J", "Q", "K"}:
        return 10
    return int(rank)


def hand_value(cards: list[dict]) -> tuple[int, bool]:
    total = sum(_card_value(c["rank"]) for c in cards)
    aces = sum(1 for c in cards if c["rank"] == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    soft = any(c["rank"] == "A" for c in cards) and total <= 21 and total + 10 > 21
    return total, soft


def is_blackjack(cards: list[dict]) -> bool:
    if len(cards) != 2:
        return False
    total, _ = hand_value(cards)
    return total == 21


class Deck:
    def __init__(self):
        self.cards = [{"rank": r, "suit": s} for s in SUITS for r in RANKS]
        random.shuffle(self.cards)

    def deal(self) -> dict:
        if not self.cards:
            self.cards = [{"rank": r, "suit": s} for s in SUITS for r in RANKS]
            random.shuffle(self.cards)
        return self.cards.pop()


class Player:
    def __init__(self, user_id: int, name: str, chips: int, is_bot: bool = False):
        self.user_id = user_id
        self.name = name
        self.chips = chips
        self.is_bot = is_bot
        self.sitting_out = False
        self.reset_round()

    def reset_round(self):
        self.cards: list[dict] = []
        self.bet = 0
        self.done = False
        self.busted = False
        self.blackjack = False
        self.doubled = False
        self.result: dict | None = None


class BlackjackGame:
    def __init__(self, start_chips: int = 1000, bet_amount: int = 25):
        self.start_chips = start_chips
        self.bet_amount = max(1, min(5000, int(bet_amount)))
        self.players: list[Player] = []
        self.phase = PHASE_WAITING
        self.deck: Deck | None = None
        self.dealer_cards: list[dict] = []
        self.current_idx = -1
        self.round_num = 0
        self.results: dict | None = None
        self.last_action: dict | None = None

    def add_player(self, user_id: int, name: str, chips: int | None = None, is_bot: bool = False) -> bool:
        if any(p.user_id == user_id for p in self.players):
            return False
        c = chips if chips is not None else self.start_chips
        self.players.append(Player(user_id, name, c, is_bot=is_bot))
        return True

    def remove_player(self, user_id: int):
        idx = next((i for i, p in enumerate(self.players) if p.user_id == user_id), None)
        if idx is None:
            return
        self.players.pop(idx)
        if self.phase == PHASE_PLAYING:
            if not self.players:
                self.current_idx = -1
                self.phase = PHASE_WAITING
                return
            if self.current_idx >= len(self.players):
                self.current_idx = len(self.players) - 1
            if idx <= self.current_idx:
                self.current_idx = max(0, self.current_idx - 1)
            self._advance_turn()

    def _active_indices(self) -> list[int]:
        return [i for i, p in enumerate(self.players) if not p.sitting_out and p.chips > 0]

    def _acting_indices(self) -> list[int]:
        return [
            i for i, p in enumerate(self.players)
            if not p.sitting_out and p.chips > 0 and not p.done and not p.busted
        ]

    def start_round(self) -> bool:
        active = self._active_indices()
        if len(active) < 1:
            return False

        self.round_num += 1
        self.deck = Deck()
        self.dealer_cards = []
        self.results = None
        self.last_action = None
        self.phase = PHASE_PLAYING

        for p in self.players:
            p.reset_round()

        # Fixed table bet keeps game simple and avoids griefing.
        for i in active:
            p = self.players[i]
            bet = min(self.bet_amount, p.chips)
            if bet <= 0:
                p.sitting_out = True
                continue
            p.bet = bet
            p.chips -= bet

        still_active = [i for i in active if self.players[i].bet > 0]
        if not still_active:
            self.phase = PHASE_WAITING
            return False

        for i in still_active:
            p = self.players[i]
            p.cards = [self.deck.deal(), self.deck.deal()]
            p.blackjack = is_blackjack(p.cards)
            if p.blackjack:
                p.done = True

        self.dealer_cards = [self.deck.deal(), self.deck.deal()]
        dealer_bj = is_blackjack(self.dealer_cards)
        if dealer_bj:
            for i in still_active:
                self.players[i].done = True

        self._set_first_turn()
        if self.current_idx == -1:
            self._finish_round()
        return True

    def _set_first_turn(self):
        self.current_idx = -1
        for i in range(len(self.players)):
            p = self.players[i]
            if p.bet > 0 and not p.done and not p.busted and not p.sitting_out:
                self.current_idx = i
                return

    def _advance_turn(self):
        if self.phase != PHASE_PLAYING:
            return
        acting = self._acting_indices()
        if not acting:
            self.current_idx = -1
            self._finish_round()
            return
        if self.current_idx not in acting:
            self.current_idx = acting[0]
            return
        pos = acting.index(self.current_idx)
        self.current_idx = acting[(pos + 1) % len(acting)]
        if self.current_idx == acting[0]:
            if all(self.players[i].done or self.players[i].busted for i in acting):
                self.current_idx = -1
                self._finish_round()

    def action(self, user_id: int, act: str) -> tuple[bool, str]:
        if self.phase != PHASE_PLAYING:
            return False, "No active round"
        idx = next((i for i, p in enumerate(self.players) if p.user_id == user_id), None)
        if idx is None:
            return False, "Not in game"
        if idx != self.current_idx:
            return False, "Not your turn"
        p = self.players[idx]
        if p.done or p.busted or p.bet <= 0:
            return False, "Cannot act"

        if act == "hit":
            p.cards.append(self.deck.deal())
            total, _ = hand_value(p.cards)
            self.last_action = {"player": idx, "action": "hit", "total": total}
            if total > 21:
                p.busted = True
                p.done = True
                self.last_action["busted"] = True
            self._advance_turn()
            return True, "hit"

        if act == "stand":
            p.done = True
            self.last_action = {"player": idx, "action": "stand"}
            self._advance_turn()
            return True, "stand"

        if act == "double":
            if p.doubled:
                return False, "Already doubled"
            if len(p.cards) != 2:
                return False, "Double only on first move"
            if p.chips < p.bet:
                return False, "Not enough chips"
            p.chips -= p.bet
            p.bet *= 2
            p.doubled = True
            p.cards.append(self.deck.deal())
            total, _ = hand_value(p.cards)
            if total > 21:
                p.busted = True
            p.done = True
            self.last_action = {"player": idx, "action": "double", "total": total}
            self._advance_turn()
            return True, "double"

        return False, "Unknown action"

    def _dealer_play(self):
        while True:
            total, soft = hand_value(self.dealer_cards)
            if total > 21:
                return
            if total < 17:
                self.dealer_cards.append(self.deck.deal())
                continue
            if total == 17 and soft:
                return
            return

    def _finish_round(self):
        self._dealer_play()
        dealer_total, _ = hand_value(self.dealer_cards)
        dealer_bust = dealer_total > 21
        dealer_bj = is_blackjack(self.dealer_cards)

        res_players = []
        for i, p in enumerate(self.players):
            if p.bet <= 0:
                continue
            p_total, _ = hand_value(p.cards)
            payout = 0
            outcome = "loss"
            if p.busted:
                payout = 0
                outcome = "loss"
            elif p.blackjack and not dealer_bj:
                payout = int(p.bet * 2.5)
                outcome = "blackjack"
            elif dealer_bust:
                payout = p.bet * 2
                outcome = "win"
            elif dealer_bj and not p.blackjack:
                payout = 0
                outcome = "loss"
            elif p_total > dealer_total:
                payout = p.bet * 2
                outcome = "win"
            elif p_total == dealer_total:
                payout = p.bet
                outcome = "push"
            else:
                payout = 0
                outcome = "loss"

            if payout > 0:
                p.chips += payout
            p.result = {
                "outcome": outcome,
                "bet": p.bet,
                "payout": payout,
                "total": p_total,
                "busted": p.busted,
                "blackjack": p.blackjack,
            }
            res_players.append({"index": i, **p.result})

        self.phase = PHASE_SHOWDOWN
        self.current_idx = -1
        self.results = {
            "dealer": {
                "cards": list(self.dealer_cards),
                "total": dealer_total,
                "busted": dealer_bust,
                "blackjack": dealer_bj,
            },
            "players": res_players,
        }

    def state_for(self, user_id: int) -> dict:
        idx = next((i for i, p in enumerate(self.players) if p.user_id == user_id), -1)
        me = self.players[idx] if idx >= 0 else None
        phase = self.phase

        players = []
        for i, p in enumerate(self.players):
            total, _ = hand_value(p.cards)
            cards = p.cards if i == idx or phase == PHASE_SHOWDOWN else [{"rank": "?", "suit": "?"}] * len(p.cards)
            players.append({
                "id": p.user_id,
                "name": p.name,
                "chips": p.chips,
                "bet": p.bet,
                "isBot": p.is_bot,
                "sittingOut": p.sitting_out,
                "done": p.done,
                "busted": p.busted,
                "blackjack": p.blackjack,
                "cards": cards,
                "total": total if (i == idx or phase == PHASE_SHOWDOWN) else None,
                "result": p.result if phase == PHASE_SHOWDOWN else None,
            })

        actions = []
        if phase == PHASE_PLAYING and idx == self.current_idx and me and not me.done and not me.busted:
            actions = ["hit", "stand"]
            if len(me.cards) == 2 and me.chips >= me.bet and not me.doubled:
                actions.append("double")

        dealer_cards = self.dealer_cards
        if phase != PHASE_SHOWDOWN and dealer_cards:
            dealer_view = [dealer_cards[0], {"rank": "?", "suit": "?"}]
            dealer_total = _card_value(dealer_cards[0]["rank"])
        else:
            dealer_view = dealer_cards
            dealer_total, _ = hand_value(dealer_cards)

        return {
            "phase": phase,
            "roundNum": self.round_num,
            "currentIndex": self.current_idx if phase == PHASE_PLAYING else -1,
            "myIndex": idx,
            "players": players,
            "dealer": {
                "cards": dealer_view,
                "total": dealer_total,
            },
            "actions": actions,
            "results": self.results,
            "lastAction": self.last_action,
            "tableBet": self.bet_amount,
        }
