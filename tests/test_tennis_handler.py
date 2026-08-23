from datetime import datetime
from unittest.mock import MagicMock

from steward.data.models.tennis import TennisMatch, TennisSession
from steward.data.models.user import User
from steward.features.tennis import TennisFeature, _session_stats_text
from tests.conftest import CHAT_ID, DEFAULT_USER_ID, make_context, make_repository


async def test_tennis_default_command_sends_rich_recent_sessions_table():
    repo = make_repository()
    repo.db.users = [
        User(id=DEFAULT_USER_ID, username="me"),
        User(id=2, username="opponent"),
    ]
    repo.db.tennis_sessions = [
        TennisSession(
            id=3,
            chat_id=CHAT_ID,
            player_a_id=DEFAULT_USER_ID,
            player_b_id=2,
            started_at=datetime(2026, 8, 23, 18, 0),
            matches=[TennisMatch(datetime(2026, 8, 23, 18, 0), "a", score_a=11, score_b=7)],
        )
    ]
    ctx = make_context("tennis", repo=repo)
    feature = TennisFeature()
    feature.repository = repo
    feature.bot = MagicMock()

    await feature.chat(ctx)

    call = ctx.bot.do_api_request.await_args
    assert call.args[0] == "sendRichMessage"
    markdown = call.kwargs["api_kwargs"]["rich_message"]["markdown"]
    assert "| № | Дата | Игроки | Счёт |" in markdown
    assert "| 3 | 23.08 | @me - @opponent | **1:0** |" in markdown
    assert "reply_markup" in call.kwargs["api_kwargs"]


def test_session_stats_contains_each_party_and_totals():
    repo = make_repository()
    repo.db.users = [
        User(id=DEFAULT_USER_ID, username="me"),
        User(id=2, username="opponent"),
    ]
    session = TennisSession(
        id=4,
        chat_id=CHAT_ID,
        player_a_id=DEFAULT_USER_ID,
        player_b_id=2,
        started_at=datetime(2026, 8, 23, 18, 0),
        ended_at=datetime(2026, 8, 23, 18, 25),
        matches=[
            TennisMatch(datetime(2026, 8, 23, 18, 0), "a", score_a=11, score_b=7),
            TennisMatch(datetime(2026, 8, 23, 18, 10), "b", score_a=9, score_b=11),
        ],
    )

    text = _session_stats_text(session, repo.db.users)

    assert "<code>11:7</code>" in text
    assert "<code>9:11</code>" in text
    assert "Партий: 2 · очки: 20:18" in text
    assert "Длительность: 25:00" in text
