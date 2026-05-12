"""Tests for the /ai online/offline router."""
from steward.features.ai import _last_user_text, _needs_web


def test_last_user_text_picks_most_recent():
    msgs = [
        ("user", "первый"),
        ("assistant", "ответ"),
        ("user", "второй"),
    ]
    assert _last_user_text(msgs) == "второй"


def test_last_user_text_empty():
    assert _last_user_text([]) == ""
    assert _last_user_text([("assistant", "только бот")]) == ""


class TestNeedsWeb:
    async def test_returns_true_on_yes(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return "YES"

        monkeypatch.setattr("steward.features.ai.make_text_query", fake_query)
        assert await _needs_web("что сегодня в новостях?") is True

    async def test_returns_false_on_no(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return "NO"

        monkeypatch.setattr("steward.features.ai.make_text_query", fake_query)
        assert await _needs_web("расскажи анекдот") is False

    async def test_case_insensitive(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return "yes please"

        monkeypatch.setattr("steward.features.ai.make_text_query", fake_query)
        assert await _needs_web("test") is True

    async def test_empty_text_skips_classifier(self, monkeypatch):
        called = []

        async def fake_query(*args, **kwargs):
            called.append(True)
            return "YES"

        monkeypatch.setattr("steward.features.ai.make_text_query", fake_query)
        assert await _needs_web("") is False
        assert await _needs_web("   ") is False
        assert called == []

    async def test_falls_back_to_offline_on_error(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            raise RuntimeError("classifier down")

        monkeypatch.setattr("steward.features.ai.make_text_query", fake_query)
        assert await _needs_web("что угодно") is False

    async def test_garbage_response_treated_as_no(self, monkeypatch):
        async def fake_query(*args, **kwargs):
            return "не понимаю вопроса"

        monkeypatch.setattr("steward.features.ai.make_text_query", fake_query)
        assert await _needs_web("вопрос") is False
