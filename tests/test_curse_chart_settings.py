import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from steward.api import settings_routes
from steward.data.models.chat_settings import ChatSettings
from steward.data.models.curse import CurseParticipant
from steward.data.models.user import User
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.curse_punishment_digest import _broadcast_curse_report
from steward.features.settings import SettingsFeature
from tests.conftest import CHAT_ID, DEFAULT_USER_ID, make_repository


def _settings_request(repository, body, chat_id=CHAT_ID):
    request = MagicMock()
    request.app = {"repository": repository}
    request.match_info = {"chat_id": str(chat_id)}
    request.json = AsyncMock(return_value=body)
    return request


async def test_settings_api_reads_and_updates_daily_curse_chart(monkeypatch):
    repository = make_repository()
    repository.db.admin_ids = {DEFAULT_USER_ID}
    monkeypatch.setattr(settings_routes, "require_user", lambda _: DEFAULT_USER_ID)

    response = await settings_routes.handle_chat_settings_get(
        _settings_request(repository, {})
    )
    assert json.loads(response.text)["curse_daily_chart_enabled"] is False

    response = await settings_routes.handle_chat_settings_patch(
        _settings_request(repository, {"curse_daily_chart_enabled": True})
    )
    assert json.loads(response.text)["curse_daily_chart_enabled"] is True
    assert repository.chat_settings_for(CHAT_ID).curse_daily_chart_enabled is True


async def test_settings_api_rejects_daily_chart_update_without_admin(monkeypatch):
    repository = make_repository()
    monkeypatch.setattr(settings_routes, "require_user", lambda _: DEFAULT_USER_ID)

    response = await settings_routes.handle_chat_settings_patch(
        _settings_request(repository, {"curse_daily_chart_enabled": True})
    )

    assert response.status == 403


async def test_telegram_daily_chart_toggle_is_limited_to_chat_admins():
    repository = make_repository()
    repository.db.chat_settings = [ChatSettings(chat_id=CHAT_ID)]
    feature = SettingsFeature()
    feature.repository = repository
    feature._render_curse_options = AsyncMock()

    regular_user = MagicMock(repository=repository, user_id=DEFAULT_USER_ID)
    regular_user.toast = AsyncMock()
    await feature.cb_chart_toggle(regular_user, CHAT_ID)

    regular_user.toast.assert_awaited_once_with("Только chat-admin или global-admin")
    assert repository.chat_settings_for(CHAT_ID).curse_daily_chart_enabled is False

    repository.db.chat_settings[0].chat_admins.add(DEFAULT_USER_ID)
    await feature.cb_chart_toggle(regular_user, CHAT_ID)

    assert repository.chat_settings_for(CHAT_ID).curse_daily_chart_enabled is True
    feature._render_curse_options.assert_awaited_once_with(regular_user, CHAT_ID)


async def test_telegram_daily_chart_is_nested_in_curse_options():
    repository = make_repository()
    repository.db.chat_settings = [
        ChatSettings(
            chat_id=CHAT_ID,
            chat_admins={DEFAULT_USER_ID},
            curse_daily_chart_enabled=True,
        )
    ]
    feature = SettingsFeature()
    feature.repository = repository
    context = MagicMock(repository=repository, user_id=DEFAULT_USER_ID)
    context.edit = AsyncMock()

    await feature._render_curse_options(context, CHAT_ID)

    text = context.edit.await_args.args[0]
    keyboard = context.edit.await_args.kwargs["keyboard"]
    assert "*/curse*" in text
    assert "Ежедневный график матов: включён" in text
    assert keyboard.rows[0][0].text == "✅ Ежедневный график"
    assert keyboard.rows[-1][0].text == "⏎ Назад"


async def test_daily_chart_uses_enabled_chat_without_participant_source_chat():
    repository = make_repository()
    chart_chat_id = CHAT_ID - 1
    repository.db.users = [
        User(id=DEFAULT_USER_ID, username="cursing", chat_ids=[chart_chat_id]),
    ]
    repository.db.curse_participants = [
        CurseParticipant(
            user_id=DEFAULT_USER_ID,
            subscribed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            source_chat_ids=[CHAT_ID],
        ),
    ]
    repository.db.chat_settings = [
        ChatSettings(
            chat_id=chart_chat_id,
            enabled_capabilities={"stats"},
            curse_daily_chart_enabled=True,
        ),
    ]
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    context = DelayedActionContext(repository, bot, MagicMock(), MagicMock())

    await _broadcast_curse_report(context, chart_day=date(2026, 8, 22))

    bot.send_photo.assert_awaited_once()
    assert bot.send_photo.await_args.args[0] == chart_chat_id


async def test_daily_chart_requires_stats_capability():
    repository = make_repository()
    repository.db.chat_settings = [
        ChatSettings(
            chat_id=CHAT_ID,
            curse_daily_chart_enabled=True,
        ),
    ]
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    context = DelayedActionContext(repository, bot, MagicMock(), MagicMock())

    await _broadcast_curse_report(context, chart_day=date(2026, 8, 22))

    bot.send_photo.assert_not_awaited()


async def test_daily_chart_does_not_send_empty_series():
    repository = make_repository()
    repository.db.chat_settings = [
        ChatSettings(
            chat_id=CHAT_ID,
            enabled_capabilities={"stats"},
            curse_daily_chart_enabled=True,
        ),
    ]
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    context = DelayedActionContext(repository, bot, MagicMock(), MagicMock())

    await _broadcast_curse_report(context, chart_day=date(2026, 8, 22))

    bot.send_photo.assert_not_awaited()


async def test_daily_chart_requires_explicit_chat_setting():
    repository = make_repository()
    repository.db.chat_settings = [
        ChatSettings(
            chat_id=CHAT_ID,
            enabled_capabilities={"stats"},
        ),
    ]
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    context = DelayedActionContext(repository, bot, MagicMock(), MagicMock())

    await _broadcast_curse_report(context, chart_day=date(2026, 8, 22))

    bot.send_photo.assert_not_awaited()
