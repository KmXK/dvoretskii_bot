"""AI-комментатор партий. Превращает «Партия 11:7 в пользу Алисы» в живую
короткую фразу с эмоциями и лёгким сарказмом.

Полностью опционально: если OpenRouter не сконфигурирован или таймаут —
возвращаем None и вызывающий код использует стандартное объявление.
"""
from __future__ import annotations

import logging
from typing import Sequence

from steward.data.models.tennis import TennisMatch, TennisSession
from steward.helpers.ai import OpenRouterModel, make_openrouter_query
from steward.tennis.engine import SIDE_A, SIDE_B, session_wins, sport_meta

__all__ = ["generate_match_commentary", "should_generate_commentary"]

logger = logging.getLogger(__name__)


def _system_prompt(sport: str | None) -> str:
    name = sport_meta(sport)["genitive"]
    return (
        f"Ты — живой комментатор {name}. После каждой партии выдаёшь "
        "одну короткую реплику (1 предложение, до 120 символов). Стиль: живой, "
        "с лёгким сарказмом и эмоциями, как комментатор у Sportbox. Можно подкалывать, "
        "обыгрывать счёт, замечать серии и отыгрыши, реагировать на разгромы и deuce. "
        "Никаких эмодзи, кавычек, скобок, пояснений. Только сама реплика, без префиксов "
        "вроде «Комментатор:». Не повторяй один и тот же шаблон в подряд идущих репликах."
    )


def _current_win_streak(matches: Sequence[TennisMatch]) -> tuple[str, int]:
    """Кто и сколько партий подряд выиграл к этому моменту (включительно)."""
    if not matches:
        return "", 0
    last = matches[-1].winner
    n = 0
    for m in reversed(matches):
        if m.winner == last:
            n += 1
        else:
            break
    return last, n


def _recent_summary(matches: Sequence[TennisMatch], n: int = 5) -> str:
    """Текстовая сводка последних N партий — для контекста модели."""
    tail = list(matches[-n:])
    parts: list[str] = []
    for m in tail:
        if m.score_a is None or m.score_b is None:
            parts.append(f"победил {'A' if m.winner == SIDE_A else 'B'}")
        else:
            parts.append(f"{m.score_a}:{m.score_b} ({'A' if m.winner == SIDE_A else 'B'})")
    return " · ".join(parts) if parts else "—"


def should_generate_commentary(session: TennisSession, match: TennisMatch) -> bool:
    """Стоит ли генерировать AI-комментарий для этой партии?

    Комментируем только заметные моменты, не каждую партию.
    """
    matches = session.matches  # новая партия уже добавлена
    n = len(matches)

    # Deuce-завершение: у проигравшего ≥10 очков
    if match.score_a is not None and match.score_b is not None:
        lo = min(match.score_a, match.score_b)
        if lo >= 10:
            return True

    # Серия 3+ побед подряд у одного игрока
    _, streak = _current_win_streak(matches)
    if streak >= 3:
        return True

    # Отыгрыш: счёт сессии сравнялся после отставания ≥2
    wins_a, wins_b = session_wins(session)
    if wins_a == wins_b and n >= 4:
        return True

    # Каждые 5 партий — чтобы не молчать совсем
    if n >= 5 and n % 5 == 0:
        return True

    return False


async def generate_match_commentary(
    session: TennisSession,
    match: TennisMatch,
    *,
    name_a: str,
    name_b: str,
    sport: str | None = None,
) -> str | None:
    wins_a, wins_b = session_wins(session)
    streak_side, streak_n = _current_win_streak(session.matches)
    streak_name = name_a if streak_side == SIDE_A else name_b
    winner_name = name_a if match.winner == SIDE_A else name_b
    loser_name = name_b if match.winner == SIDE_A else name_a

    if match.score_a is not None and match.score_b is not None:
        winner_score = match.score_a if match.winner == SIDE_A else match.score_b
        loser_score = match.score_b if match.winner == SIDE_A else match.score_a
        score_phrase = f"{winner_score}:{loser_score}"
    else:
        score_phrase = "счёт не записан"

    recent = _recent_summary(session.matches)

    user_msg = (
        f"Игроки: {name_a} (A) против {name_b} (B).\n"
        f"Только что: {winner_name} обыграл {loser_name} со счётом {score_phrase}.\n"
        f"После партии общий счёт сессии: {name_a} {wins_a} — {wins_b} {name_b} "
        f"(всего сыграно {len(session.matches)} партий).\n"
        f"Текущая серия: {streak_name} выиграл подряд {streak_n}.\n"
        f"Последние партии: {recent}.\n"
        f"Дай комментарий."
    )

    try:
        text = await make_openrouter_query(
            user_id=session.initiator_id or session.player_a_id,
            model=OpenRouterModel.FAST,
            messages=[("user", user_msg)],
            system_prompt=_system_prompt(sport if sport is not None else getattr(session, "sport", None)),
            max_tokens=120,
            timeout_seconds=8.0,
        )
    except Exception as e:
        logger.info("tennis commentator failed: %s", e)
        return None

    text = (text or "").strip().strip('"').strip("«»").strip()
    if not text:
        return None
    # Жёсткий cap — Yandex TTS чтобы не тянул долго и Telegram caption тоже короче 1024
    if len(text) > 280:
        text = text[:280].rsplit(".", 1)[0] + "."
    return text
