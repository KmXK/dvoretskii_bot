"""Tests for RemindFeature/RemindersFeature: add, remove, list."""
import datetime

from steward.delayed_action.reminder import ReminderDelayedAction, ReminderGenerator
from steward.features.remind import RemindFeature, RemindersFeature
from tests.conftest import invoke, make_repository

CHAT_ID = -100123456789


def _reminder(id: str, text: str) -> ReminderDelayedAction:
    return ReminderDelayedAction(
        id=int(id) if str(id).isdigit() else 1,
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
        repo.db.delayed_actions = [_reminder("1", "купить молоко")]
        reply, ok = await invoke(RemindersFeature, "/reminders", repo)
        assert ok
        assert "купить молоко" in reply

    async def test_accessible_via_remind_list(self):
        repo = make_repository()
        repo.db.delayed_actions = [_reminder("1", "позвонить")]
        reply, ok = await invoke(RemindFeature, "/remind list", repo)
        assert ok
        assert "позвонить" in reply


class TestRemindRemove:
    async def test_removes_reminder(self):
        repo = make_repository()
        repo.db.delayed_actions = [_reminder("1", "купить молоко")]
        reply, ok = await invoke(RemindFeature, "/remind remove 1", repo)
        assert ok
        assert "Удалено" in reply
        assert len(repo.db.delayed_actions) == 0

    async def test_not_found(self):
        repo = make_repository()
        reply, ok = await invoke(RemindFeature, "/remind remove 999", repo)
        assert ok
        assert "не найдено" in reply


class TestRemindEdit:
    async def test_edits_reminder(self):
        repo = make_repository()
        repo.db.delayed_actions = [_reminder("1", "старый текст")]
        reply, ok = await invoke(RemindFeature, "/remind edit 1 новый текст", repo)
        assert ok
        assert "новый текст" in reply
        assert repo.db.delayed_actions[0].text == "новый текст"

    async def test_not_found(self):
        repo = make_repository()
        reply, ok = await invoke(RemindFeature, "/remind edit 999 новый текст", repo)
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
        assert isinstance(repo.db.delayed_actions[0].id, int)
        assert repo.db.delayed_actions[0].id > 0

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


class TestRemindMigrationV18:
    def test_renumbers_reminders_deterministically(self):
        repo = make_repository()
        data = {
            "version": 17,
            "delayed_actions": [
                {
                    "__class_mark__": "delayed_action/reminder",
                    "id": "deadbeef",
                    "chat_id": CHAT_ID,
                    "user_id": 1,
                    "text": "later",
                    "created_at": "2026-01-02T00:00:00+00:00",
                    "generator": {
                        "__class_mark__": "generator/reminder",
                        "next_fire": "2026-01-02T01:00:00+00:00",
                        "interval_seconds": None,
                        "repeat_remaining": None,
                        "days": None,
                    },
                    "fired_count": 0,
                },
                {
                    "__class_mark__": "delayed_action/reminder",
                    "id": "a1b2c3d4",
                    "chat_id": CHAT_ID,
                    "user_id": 1,
                    "text": "earlier",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "generator": {
                        "__class_mark__": "generator/reminder",
                        "next_fire": "2026-01-01T01:00:00+00:00",
                        "interval_seconds": None,
                        "repeat_remaining": None,
                        "days": None,
                    },
                    "fired_count": 0,
                },
            ],
            "completed_reminders": [
                {
                    "__class_mark__": "reminder/completed",
                    "id": "ffffffff",
                    "chat_id": CHAT_ID,
                    "user_id": 1,
                    "text": "completed",
                    "created_at": "2026-01-03T00:00:00+00:00",
                    "completed_at": "2026-01-03T00:00:01+00:00",
                    "fired_count": 1,
                }
            ],
        }

        migrated = repo._migrate(data)
        assert migrated["version"] == 18

        # Order: earlier (2026-01-01) -> later (2026-01-02) -> completed (2026-01-03)
        assert migrated["delayed_actions"][0]["id"] == 2
        assert migrated["delayed_actions"][1]["id"] == 1
        assert migrated["completed_reminders"][0]["id"] == 3
