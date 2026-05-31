"""Тесты паделльного движка счёта (очки→гейм→сет→тай-брейк→матч)."""
from steward.tennis.engine import (
    SIDE_A,
    SIDE_B,
    is_padel,
    is_team_sport,
    normalize_sport,
    padel_server_side,
    padel_state,
)


def a(n):
    return [SIDE_A] * n


def b(n):
    return [SIDE_B] * n


def game(side, n=1):
    """n геймов всухую за side при «золотом мяче» (4 очка = гейм)."""
    return [side] * (4 * n)


# ── распознавание спорта ──────────────────────────────────────────────────────

def test_padel_is_recognized():
    assert normalize_sport("padel") == "padel"
    assert is_padel("padel") is True
    assert is_padel("squash") is False
    assert is_team_sport("padel") is True
    assert is_team_sport("table_tennis") is False


# ── очки в гейме ────────────────────────────────────────────────────────────

def test_point_labels_progression():
    assert padel_state(a(1)).point_label_a == "15"
    assert padel_state(a(2)).point_label_a == "30"
    assert padel_state(a(3)).point_label_a == "40"


def test_game_won_resets_points():
    st = padel_state(a(4))
    assert st.games_a == 1
    assert st.points_a == 0
    assert st.point_label_a == "0"


def test_deuce_advantage_without_golden():
    base = a(3) + b(3)
    st = padel_state(base, golden_point=False)
    assert (st.point_label_a, st.point_label_b) == ("40", "40")
    st_adv = padel_state(base + [SIDE_A], golden_point=False)
    assert (st_adv.point_label_a, st_adv.point_label_b) == ("Ad", "40")
    # назад к ровно
    st_back = padel_state(base + [SIDE_A, SIDE_B], golden_point=False)
    assert (st_back.point_label_a, st_back.point_label_b) == ("40", "40")
    # два подряд после ровно — гейм
    st_game = padel_state(base + [SIDE_A, SIDE_A], golden_point=False)
    assert st_game.games_a == 1


def test_golden_point_decides_at_deuce():
    base = a(3) + b(3)  # 40:40
    st = padel_state(base, golden_point=True)
    assert (st.point_label_a, st.point_label_b) == ("40", "40")
    st_after = padel_state(base + [SIDE_A], golden_point=True)
    assert st_after.games_a == 1  # сразу гейм, без преимущества


# ── сеты ──────────────────────────────────────────────────────────────────────

def test_set_won_six_love():
    st = padel_state(game(SIDE_A, 6), sets_to_win=2)
    assert st.sets_a == 1
    assert st.completed_sets == [(6, 0)]
    assert not st.match_complete


def test_set_seven_five():
    log = (game(SIDE_A) + game(SIDE_B)) * 5   # 5:5
    log += game(SIDE_A) + game(SIDE_A)        # 6:5, 7:5
    st = padel_state(log)
    assert st.completed_sets == [(7, 5)]
    assert st.sets_a == 1


def test_six_five_is_not_a_set():
    log = (game(SIDE_A) + game(SIDE_B)) * 5 + game(SIDE_A)  # 6:5
    st = padel_state(log)
    assert st.completed_sets == []
    assert (st.games_a, st.games_b) == (6, 5)
    assert not st.in_tiebreak


# ── тай-брейк ─────────────────────────────────────────────────────────────────

def test_tiebreak_triggered_at_six_all():
    log = (game(SIDE_A) + game(SIDE_B)) * 6   # 6:6
    st = padel_state(log)
    assert st.in_tiebreak is True
    assert (st.games_a, st.games_b) == (6, 6)
    assert (st.points_a, st.points_b) == (0, 0)


def test_tiebreak_labels_are_numbers():
    log = (game(SIDE_A) + game(SIDE_B)) * 6 + a(3) + b(1)
    st = padel_state(log)
    assert st.in_tiebreak
    assert (st.point_label_a, st.point_label_b) == ("3", "1")


def test_tiebreak_won_takes_set_seven_six():
    log = (game(SIDE_A) + game(SIDE_B)) * 6 + a(7)
    st = padel_state(log)
    assert st.completed_sets == [(7, 6)]
    assert st.sets_a == 1
    assert not st.in_tiebreak


def test_tiebreak_requires_margin_two():
    log = (game(SIDE_A) + game(SIDE_B)) * 6 + a(6) + b(6)  # 6:6 в тай-брейке
    st = padel_state(log)
    assert st.in_tiebreak
    assert st.sets_a == 0 and st.sets_b == 0
    st2 = padel_state(log + a(2))  # 8:6
    assert st2.completed_sets == [(7, 6)]


# ── матч ──────────────────────────────────────────────────────────────────────

def test_match_best_of_three():
    log = game(SIDE_A, 6) + game(SIDE_A, 6)  # два сета 6:0
    st = padel_state(log, sets_to_win=2)
    assert st.match_complete
    assert st.winner == SIDE_A
    assert st.sets_a == 2


def test_points_after_match_ignored():
    log = game(SIDE_A, 6) + game(SIDE_A, 6) + a(20)
    st = padel_state(log, sets_to_win=2)
    assert st.winner == SIDE_A
    assert st.sets_a == 2  # лишние очки не накручивают


def test_single_set_match():
    st = padel_state(game(SIDE_A, 6), sets_to_win=1)
    assert st.match_complete
    assert st.winner == SIDE_A


def test_undo_reverts_completed_game():
    log = game(SIDE_A)              # гейм закрыт, games_a=1
    assert padel_state(log).games_a == 1
    # снимаем последний поинт — гейм «распадается» обратно в 40:0
    st = padel_state(log[:-1])
    assert st.games_a == 0
    assert st.point_label_a == "40"


# ── индикатор подачи ──────────────────────────────────────────────────────────

def test_server_alternates_each_game():
    assert padel_server_side([], SIDE_A) == SIDE_A
    assert padel_server_side(game(SIDE_A), SIDE_A) == SIDE_B      # после 1 гейма
    assert padel_server_side(game(SIDE_A) + game(SIDE_B), SIDE_A) == SIDE_A  # после 2
