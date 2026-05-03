"""Tests for BirthdayFeature: view, add, remove."""
from steward.data.models.birthday import Birthday
from steward.features.birthday import BirthdayFeature
from tests.conftest import invoke, make_repository

CHAT_ID = -100123456789


def _birthday(name: str, day: int, month: int) -> Birthday:
    return Birthday(name=name, day=day, month=month, chat_id=CHAT_ID)


class TestBirthdayView:
    async def test_empty_list(self):
        repo = make_repository()
        reply, ok = await invoke(BirthdayFeature, "/birthday", repo)
        assert ok
        assert "пуст" in reply

    async def test_shows_birthdays(self):
        repo = make_repository()
        repo.db.birthdays = [_birthday("Иван", 15, 3), _birthday("Маша", 20, 7)]
        reply, ok = await invoke(BirthdayFeature, "/birthday", repo)
        assert ok
        assert "Иван" in reply
        assert "Маша" in reply

    async def test_adds_birthday(self):
        repo = make_repository()
        repo.db.admin_ids = {12345}
        reply, ok = await invoke(BirthdayFeature, "/birthday Иван 15.03", repo)
        assert ok
        assert len(repo.db.birthdays) == 1
        b = repo.db.birthdays[0]
        assert b.name == "Иван"
        assert b.day == 15
        assert b.month == 3
        assert "Запомнил" in reply

    async def test_updates_existing_birthday(self):
        repo = make_repository()
        repo.db.birthdays = [_birthday("Иван", 10, 3)]
        reply, ok = await invoke(BirthdayFeature, "/birthday Иван 15.03", repo)
        assert ok
        assert len(repo.db.birthdays) == 1
        assert repo.db.birthdays[0].day == 15

    async def test_invalid_date(self):
        repo = make_repository()
        reply, ok = await invoke(BirthdayFeature, "/birthday Иван 32.03", repo)
        assert ok
        assert "Некорректная" in reply
        assert len(repo.db.birthdays) == 0


class TestBirthdayRemove:
    async def test_removes_birthday(self):
        repo = make_repository()
        repo.db.admin_ids = {12345}
        repo.db.birthdays = [_birthday("Иван", 15, 3)]
        reply, ok = await invoke(BirthdayFeature, "/birthday remove Иван", repo)
        assert ok
        assert len(repo.db.birthdays) == 0
        assert "Удалил" in reply

    async def test_not_found(self):
        repo = make_repository()
        repo.db.admin_ids = {12345}
        reply, ok = await invoke(BirthdayFeature, "/birthday remove Иван", repo)
        assert ok
        assert "нет" in reply
