"""Tests for RemindFeature/RemindersFeature: add, remove, list."""
import datetime

from steward.delayed_action.reminder import ReminderDelayedAction, ReminderGenerator
from steward.features.remind import RemindFeature, RemindersFeature
from tests.conftest import invoke, make_repository

CHAT_ID = -100123456789


def _reminder(id: str, text: str) -> ReminderDelayedAction:
    return ReminderDelayedAction(
        id=id,
        chat_id=CHAT_ID,
        user_id=12345,
        text=text,
        created_at=datetime.datetime.now(datetime.timezone.utc),
        generator=ReminderGenerator(
            next_fire=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
        ),
    )


class TestReminders:
    async def test_empty(self):
        repo = make_repository()
        reply, ok = await invoke(RemindersFeature, "/reminders", repo)
        assert ok
        assert "нет" in reply

    async def test_shows_active_reminders(self):
        repo = make_repository()
        repo.db.delayed_actions = [_reminder("abc1", "купить молоко")]
        reply, ok = await invoke(RemindersFeature, "/reminders", repo)
        assert ok
        assert "купить молоко" in reply

    async def test_accessible_via_remind_list(self):
        repo = make_repository()
        repo.db.delayed_actions = [_reminder("abc1", "позвонить")]
        reply, ok = await invoke(RemindFeature, "/remind list", repo)
        assert ok
        assert "позвонить" in reply


class TestRemindRemove:
    async def test_removes_reminder(self):
        repo = make_repository()
        repo.db.delayed_actions = [_reminder("abc1", "купить молоко")]
        reply, ok = await invoke(RemindFeature, "/remind remove abc1", repo)
        assert ok
        assert "Удалено" in reply
        assert len(repo.db.delayed_actions) == 0

    async def test_not_found(self):
        repo = make_repository()
        reply, ok = await invoke(RemindFeature, "/remind remove xyz", repo)
        assert ok
        assert "не найдено" in reply


class TestRemindEdit:
    async def test_edits_reminder(self):
        repo = make_repository()
        repo.db.delayed_actions = [_reminder("abc1", "старый текст")]
        reply, ok = await invoke(RemindFeature, "/remind edit abc1 новый текст", repo)
        assert ok
        assert "новый текст" in reply
        assert repo.db.delayed_actions[0].text == "новый текст"

    async def test_not_found(self):
        repo = make_repository()
        reply, ok = await invoke(RemindFeature, "/remind edit xyz новый текст", repo)
        assert ok
        assert "не найдено" in reply


class TestRemindAdd:
    async def test_adds_reminder_with_interval(self):
        repo = make_repository()
        reply, ok = await invoke(RemindFeature, "/remind 10m купить молоко", repo)
        assert ok
        assert "✅" in reply
        assert len(repo.db.delayed_actions) == 1
        assert repo.db.delayed_actions[0].text == "купить молоко"

    async def test_invalid_time(self):
        repo = make_repository()
        reply, ok = await invoke(RemindFeature, "/remind notatime купить молоко", repo)
        assert ok
        assert "распознать" in reply
        assert len(repo.db.delayed_actions) == 0

    async def test_no_text(self):
        repo = make_repository()
        reply, ok = await invoke(RemindFeature, "/remind 10m", repo)
        assert ok
        assert "текст" in reply
        assert len(repo.db.delayed_actions) == 0
