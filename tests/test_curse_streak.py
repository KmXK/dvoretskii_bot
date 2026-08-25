from datetime import date, datetime, timezone
from io import BytesIO

from PIL import Image

from steward.data.models.curse import CurseParticipant, CurseStreak
from steward.data.models.user import User
from steward.helpers.curse_chart import build_curse_chart_series, render_curse_chart_png
from steward.helpers.curse_streak import (
    curse_report_chat_ids,
    finalize_curse_streaks,
    format_curse_streak_forecast,
    format_curse_streak_outcome,
    hourly_curse_counts,
    participant_ids_in_chat,
    record_curses,
)
from tests.conftest import CHAT_ID, DEFAULT_USER_ID, make_repository


def _repo():
    repo = make_repository()
    repo.db.users = [User(id=DEFAULT_USER_ID, username="testuser")]
    repo.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            source_chat_ids=[CHAT_ID],
        )
    ]
    return repo


def test_clean_day_increments_global_streak_once():
    repo = _repo()
    repo.db.curse_streaks = [
        CurseStreak(
            user_id=DEFAULT_USER_ID,
            days=4,
            last_finalized_date="2026-08-21",
        )
    ]

    outcome = finalize_curse_streaks(repo, date(2026, 8, 22))

    assert outcome[0].days == 5
    assert outcome[0].curses == 0
    assert finalize_curse_streaks(repo, date(2026, 8, 22)) == []


def test_curse_resets_streak_and_final_message_shows_daily_count():
    repo = _repo()
    repo.db.curse_streaks = [
        CurseStreak(
            user_id=DEFAULT_USER_ID,
            days=9,
            last_finalized_date="2026-08-21",
        )
    ]

    assert record_curses(repo, DEFAULT_USER_ID, 2, date(2026, 8, 22))
    assert record_curses(repo, DEFAULT_USER_ID, 1, date(2026, 8, 22))
    outcome = finalize_curse_streaks(repo, date(2026, 8, 22))
    text = format_curse_streak_outcome(repo, CHAT_ID, outcome)

    assert outcome[0].days == 0
    assert outcome[0].curses == 3
    assert "стрик сброшен" in text
    assert "3 мата за сутки" in text


def test_forecast_shows_value_at_midnight():
    repo = _repo()
    repo.db.curse_streaks = [
        CurseStreak(
            user_id=DEFAULT_USER_ID,
            days=6,
            last_finalized_date="2026-08-21",
        )
    ]

    text = format_curse_streak_forecast(repo, CHAT_ID, date(2026, 8, 22))

    assert "сейчас 6 дней" in text
    assert "будет 7 дней" in text


def test_streak_is_global_but_renders_in_every_subscribed_chat():
    other_chat = -100999
    repo = _repo()
    repo.db.curse_participants[0].source_chat_ids.append(other_chat)
    repo.db.curse_streaks = [CurseStreak(user_id=DEFAULT_USER_ID, days=2)]

    first = format_curse_streak_forecast(repo, CHAT_ID, date(2026, 8, 22))
    second = format_curse_streak_forecast(repo, other_chat, date(2026, 8, 22))

    assert "сейчас 2 дня" in first
    assert "сейчас 2 дня" in second


def test_duplicate_participant_is_rendered_once():
    repo = _repo()
    repo.db.curse_participants.append(repo.db.curse_participants[0])

    assert participant_ids_in_chat(repo, CHAT_ID) == [DEFAULT_USER_ID]


def test_participant_is_not_visible_without_subscription_in_chat():
    other_chat = -100999
    repo = _repo()
    repo.db.users[0].chat_ids = [CHAT_ID, other_chat]
    repo.db.curse_streaks = [CurseStreak(user_id=DEFAULT_USER_ID, days=2)]

    text = format_curse_streak_forecast(repo, other_chat, date(2026, 8, 22))

    assert text == ""
    assert curse_report_chat_ids(repo) == [CHAT_ID]


def test_hourly_counts_have_24_points_and_accumulate_by_hour():
    repo = _repo()
    day = date(2026, 8, 22)

    record_curses(repo, DEFAULT_USER_ID, 2, day, hour=3)
    record_curses(repo, DEFAULT_USER_ID, 1, day, hour=3)
    record_curses(repo, DEFAULT_USER_ID, 4, day, hour=17)

    counts = hourly_curse_counts(repo, DEFAULT_USER_ID, day)
    assert len(counts) == 24
    assert counts[3] == 3
    assert counts[17] == 4
    assert sum(counts) == 7


def test_chart_contains_zero_line_for_participant_without_curses():
    second_user_id = DEFAULT_USER_ID + 1
    repo = _repo()
    repo.db.users[0].chat_ids = [CHAT_ID]
    repo.db.users.append(User(id=second_user_id, username="clean", chat_ids=[CHAT_ID]))
    repo.db.curse_participants.append(
        CurseParticipant(
            user_id=second_user_id,
            subscribed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            source_chat_ids=[CHAT_ID],
        )
    )
    day = date(2026, 8, 22)
    record_curses(repo, DEFAULT_USER_ID, 3, day, hour=10)

    series = build_curse_chart_series(repo, CHAT_ID, day)
    clean = next(item for item in series if item.user_id == second_user_id)
    png = render_curse_chart_png(series, day)

    assert len(series) == 2
    assert len(clean.cumulative_counts) == 24
    assert clean.cumulative_counts == (0,) * 24
    assert png is not None
    image = Image.open(BytesIO(png))
    assert image.format == "PNG"
    assert image.width == 1200
