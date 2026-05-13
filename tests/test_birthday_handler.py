"""Tests for BirthdayFeature: view, manual add (with/without year), remove, AI lookup."""
import json
from unittest.mock import MagicMock

from steward.data.models.birthday import Birthday
from steward.features.birthday import BirthdayFeature
from tests.conftest import invoke, make_repository

CHAT_ID = -100123456789


def _patch_status_capture(monkeypatch):
    """Patch edit_with_animated_status to skip TG animation and capture the
    renderer output. Returns the captured-dict and the patch helper sets a
    'text', 'keyboard', 'html' key on first render."""
    captured: dict = {}

    async def fake_status(target, work, renderer, *, placeholder=None):
        try:
            result = await work
        except Exception as e:
            result = e
        text, keyboard, is_html = renderer(result)
        captured["text"] = text
        captured["keyboard"] = keyboard
        captured["html"] = is_html
        return MagicMock()

    monkeypatch.setattr(
        "steward.features.birthday.edit_with_animated_status", fake_status
    )
    return captured


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
                "candidates": [
                    {
                        "day": 15, "month": 3, "year": 1990,
                        "sources": ["https://example.com/a", "https://example.com/b"],
                    },
                ],
                "description": "Известен тем, что снимает кринж-видео",
            })

        monkeypatch.setattr(
            "steward.features.birthday.make_openrouter_query", fake_query
        )
        captured = _patch_status_capture(monkeypatch)
        repo = make_repository()
        _, ok = await invoke(BirthdayFeature, "/birthday Иван Золо", repo)
        assert ok
        text = captured["text"]
        assert "Сохранить" in text
        assert "15 марта" in text
        assert "1990" in text
        assert "Известен" in text
        assert "example.com" in text
        assert captured["keyboard"] is not None
        assert len(repo.db.birthdays) == 0

    async def test_lookup_conflict_shows_picker(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return json.dumps({
                "candidates": [
                    {
                        "day": 15, "month": 3, "year": 1990,
                        "sources": ["https://example.com/wiki"],
                    },
                    {
                        "day": 14, "month": 3, "year": 1990,
                        "sources": ["https://example.com/imdb"],
                    },
                ],
                "description": "Шумный публичный персонаж",
            })

        monkeypatch.setattr(
            "steward.features.birthday.make_openrouter_query", fake_query
        )
        captured = _patch_status_capture(monkeypatch)
        repo = make_repository()
        _, ok = await invoke(BirthdayFeature, "/birthday Спорный Человек", repo)
        assert ok
        text = captured["text"]
        assert "расходятся" in text
        assert "15 марта" in text
        assert "14 марта" in text
        assert "wiki" in text
        assert "imdb" in text
        kb = captured["keyboard"]
        assert kb is not None
        all_labels = [b.text for row in kb.rows for b in row]
        assert any("15 марта" in label for label in all_labels)
        assert any("14 марта" in label for label in all_labels)
        assert any("Отмена" in label for label in all_labels)
        assert len(repo.db.birthdays) == 0

    async def test_lookup_ai_error(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return json.dumps({"error": "не нашёл"})

        monkeypatch.setattr(
            "steward.features.birthday.make_openrouter_query", fake_query
        )
        captured = _patch_status_capture(monkeypatch)
        repo = make_repository()
        _, ok = await invoke(BirthdayFeature, "/birthday Кто-то Неизвестный", repo)
        assert ok
        assert "Не нашёл" in captured["text"]
        assert captured["keyboard"] is None
        assert len(repo.db.birthdays) == 0

    async def test_lookup_invalid_json(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return "что-то странное без json"

        monkeypatch.setattr(
            "steward.features.birthday.make_openrouter_query", fake_query
        )
        captured = _patch_status_capture(monkeypatch)
        repo = make_repository()
        _, ok = await invoke(BirthdayFeature, "/birthday Vasya", repo)
        assert ok
        text = captured["text"]
        assert "разобрать ответ AI" in text
        assert "bad_json" in text
        assert len(repo.db.birthdays) == 0

    async def test_lookup_query_exception(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(
            "steward.features.birthday.make_openrouter_query", fake_query
        )
        captured = _patch_status_capture(monkeypatch)
        repo = make_repository()
        _, ok = await invoke(BirthdayFeature, "/birthday Vasya", repo)
        assert ok
        assert "Не получилось" in captured["text"]
        assert "network down" in captured["text"]


class TestParseLookupResponse:
    def test_valid(self):
        raw = json.dumps({
            "candidates": [
                {"day": 1, "month": 2, "year": 1990, "sources": ["a", "b"]},
            ],
            "description": "x",
        })
        out = BirthdayFeature._parse_lookup_response(raw)
        assert len(out["candidates"]) == 1
        c = out["candidates"][0]
        assert (c["day"], c["month"], c["year"]) == (1, 2, 1990)
        assert c["sources"] == ["a", "b"]

    def test_valid_conflict(self):
        raw = json.dumps({
            "candidates": [
                {"day": 1, "month": 2, "year": 1990, "sources": ["a"]},
                {"day": 2, "month": 2, "year": 1990, "sources": ["b"]},
                {"day": 3, "month": 2, "year": 1990, "sources": ["c"]},
            ],
            "description": "x",
        })
        out = BirthdayFeature._parse_lookup_response(raw)
        assert len(out["candidates"]) == 3
        assert [c["day"] for c in out["candidates"]] == [1, 2, 3]

    def test_dedupes_candidates(self):
        raw = json.dumps({
            "candidates": [
                {"day": 1, "month": 2, "year": 1990, "sources": ["a"]},
                {"day": 1, "month": 2, "year": 1990, "sources": ["b"]},
            ],
            "description": "x",
        })
        out = BirthdayFeature._parse_lookup_response(raw)
        assert len(out["candidates"]) == 1

    def test_legacy_flat_shape(self):
        raw = json.dumps({
            "day": 1, "month": 2, "year": 1990,
            "description": "x", "sources": ["a"],
        })
        out = BirthdayFeature._parse_lookup_response(raw)
        assert len(out["candidates"]) == 1
        assert out["candidates"][0]["day"] == 1

    def test_error_passthrough(self):
        raw = json.dumps({"error": "не нашёл"})
        out = BirthdayFeature._parse_lookup_response(raw)
        assert out["error"] == "not_found"
        assert out["ai_reason"] == "не нашёл"

    def test_invalid_date(self):
        raw = json.dumps({
            "candidates": [{"day": 99, "month": 1, "year": 1990, "sources": []}],
        })
        out = BirthdayFeature._parse_lookup_response(raw)
        assert out["error"] == "invalid_date"

    def test_strips_fence(self):
        raw = "```json\n" + json.dumps({
            "candidates": [
                {"day": 1, "month": 2, "year": 1990, "sources": []},
            ],
            "description": "x",
        }) + "\n```"
        out = BirthdayFeature._parse_lookup_response(raw)
        assert out["candidates"][0]["day"] == 1
