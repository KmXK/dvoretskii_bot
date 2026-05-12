"""Tests for BirthdayFeature: view, manual add (with/without year), remove, AI lookup."""
import json

from steward.data.models.birthday import Birthday
from steward.features.birthday import BirthdayFeature
from tests.conftest import invoke, make_repository

CHAT_ID = -100123456789


def _birthday(name: str, day: int, month: int, year: int | None = None) -> Birthday:
    return Birthday(name=name, day=day, month=month, chat_id=CHAT_ID, year=year)


class TestBirthdayView:
    async def test_empty_list(self):
        repo = make_repository()
        reply, ok = await invoke(BirthdayFeature, "/birthday", repo)
        assert ok
        assert "пуст" in reply

    async def test_shows_birthdays(self):
        repo = make_repository()
        repo.db.birthdays = [_birthday("Иван", 15, 3), _birthday("Маша", 20, 7, year=1995)]
        reply, ok = await invoke(BirthdayFeature, "/birthday", repo)
        assert ok
        assert "Иван" in reply
        assert "Маша" in reply
        assert "1995" in reply

    async def test_adds_birthday(self):
        repo = make_repository()
        reply, ok = await invoke(BirthdayFeature, "/birthday Иван 15.03", repo)
        assert ok
        assert len(repo.db.birthdays) == 1
        b = repo.db.birthdays[0]
        assert b.name == "Иван"
        assert b.day == 15
        assert b.month == 3
        assert b.year is None
        assert "Запомнил" in reply

    async def test_adds_birthday_with_year(self):
        repo = make_repository()
        reply, ok = await invoke(BirthdayFeature, "/birthday Иван 15.03.1990", repo)
        assert ok
        assert len(repo.db.birthdays) == 1
        b = repo.db.birthdays[0]
        assert b.year == 1990
        assert "1990" in reply

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


class TestCelebrityLookup:
    async def test_lookup_stores_pending_not_saved(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return json.dumps({
                "day": 15,
                "month": 3,
                "year": 1990,
                "description": "Известен тем, что снимает кринж-видео",
                "sources": ["https://example.com/a", "https://example.com/b"],
            })

        monkeypatch.setattr(
            "steward.features.birthday.make_openrouter_query", fake_query
        )
        repo = make_repository()
        reply, ok = await invoke(BirthdayFeature, "/birthday Иван Золо", repo)
        assert ok
        assert "Сохранить" in reply
        assert "15 марта" in reply
        assert "1990" in reply
        assert "Известен" in reply
        assert "example.com" in reply
        assert len(repo.db.birthdays) == 0

    async def test_lookup_ai_error(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return json.dumps({"error": "не нашёл"})

        monkeypatch.setattr(
            "steward.features.birthday.make_openrouter_query", fake_query
        )
        repo = make_repository()
        reply, ok = await invoke(BirthdayFeature, "/birthday Кто-то Неизвестный", repo)
        assert ok
        assert "Не нашёл" in reply
        assert len(repo.db.birthdays) == 0

    async def test_lookup_invalid_json(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return "что-то странное без json"

        monkeypatch.setattr(
            "steward.features.birthday.make_openrouter_query", fake_query
        )
        repo = make_repository()
        reply, ok = await invoke(BirthdayFeature, "/birthday Vasya", repo)
        assert ok
        assert "Не нашёл" in reply or "не понял" in reply
        assert len(repo.db.birthdays) == 0


class TestParseLookupResponse:
    def test_valid(self):
        raw = json.dumps({
            "day": 1, "month": 2, "year": 1990,
            "description": "x", "sources": ["a", "b"],
        })
        out = BirthdayFeature._parse_lookup_response(raw)
        assert out["day"] == 1
        assert out["month"] == 2
        assert out["year"] == 1990
        assert out["sources"] == ["a", "b"]

    def test_error_passthrough(self):
        raw = json.dumps({"error": "не нашёл"})
        out = BirthdayFeature._parse_lookup_response(raw)
        assert out == {"error": "не нашёл"}

    def test_invalid_date(self):
        raw = json.dumps({"day": 99, "month": 1, "year": 1990})
        out = BirthdayFeature._parse_lookup_response(raw)
        assert "error" in out

    def test_strips_fence(self):
        raw = "```json\n" + json.dumps({
            "day": 1, "month": 2, "year": 1990,
            "description": "x", "sources": [],
        }) + "\n```"
        out = BirthdayFeature._parse_lookup_response(raw)
        assert out.get("day") == 1
