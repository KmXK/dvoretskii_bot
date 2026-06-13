"""Тесты покерного движка: сохранение фишек (фишки не создаются и не теряются)."""
import random

from steward.poker.engine import PokerGame, PHASE_SHOWDOWN, PHASE_WAITING
from steward.poker.bot_ai import decide


def _play_hand(game: PokerGame):
    """Доигрывает текущую раздачу ботами до шоудауна/ожидания."""
    guard = 0
    while game.phase not in (PHASE_SHOWDOWN, PHASE_WAITING):
        guard += 1
        assert guard < 5000, "раздача зациклилась"
        idx = game.current_idx
        if idx < 0:
            break
        p = game.players[idx]
        act, amount = decide(game, idx, "medium")
        ok, _ = game.action(p.user_id, act, amount)
        if not ok:
            ok, _ = game.action(p.user_id, "fold")
            if not ok:
                game.action(p.user_id, "check")


def _chip_total(game: PokerGame) -> int:
    return sum(p.chips for p in game.players) + game.pot


def test_chip_conservation_random_games():
    """Сумма фишек за столом (фишки игроков + банк) неизменна на всём пути игры."""
    for seed in range(500):
        rng = random.Random(seed)
        n = rng.choice([2, 3, 4, 5, 6])
        random.seed(seed)  # bot_ai/engine используют глобальный random

        game = PokerGame(10, 20, 1000)
        for i in range(n):
            game.add_player(i, f"P{i}")
        expected = _chip_total(game)

        for _ in range(200):
            seated = [p for p in game.players if not p.sitting_out and p.chips > 0]
            if len(seated) < 2:
                break
            if not game.start_hand():
                break
            _play_hand(game)
            assert _chip_total(game) == expected, (
                f"seed={seed} n={n}: фишки не сохранились "
                f"({_chip_total(game)} != {expected})"
            )


def test_busted_player_does_not_inject_phantom_chips():
    """Игрок с 0 фишек и остаточным total_bet с прошлой раздачи не добавляет фишки в банк.

    Регрессия: start_hand не сбрасывал ставочное состояние у безфишечных игроков,
    и их устаревший total_bet засчитывался в сайд-поты на шоудауне.
    """
    game = PokerGame(10, 20, 1000)
    for i in range(3):
        game.add_player(i, f"P{i}")

    # Эмулируем выбывшего игрока: 0 фишек, но «грязное» состояние от прошлой раздачи.
    busted = game.players[2]
    busted.chips = 0
    busted.total_bet = 215
    busted.bet = 0
    busted.all_in = True

    expected = _chip_total(game)  # 2000 фишек у двух живых игроков
    assert game.start_hand()
    _play_hand(game)

    assert _chip_total(game) == expected
    assert busted.total_bet == 0
    assert busted.all_in is False
