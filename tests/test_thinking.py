import json
from pathlib import Path

from steward.helpers import thinking


def test_random_phrase_returns_fallback_without_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(thinking, "_CACHE_PATH", tmp_path / "none.json")
    thinking.reset_for_tests()
    phrase = thinking.random_phrase()
    assert phrase in thinking._FALLBACK_PHRASES


async def test_ensure_cached_uses_ai_and_persists(monkeypatch, tmp_path):
    cache_path = tmp_path / "thinking.json"
    monkeypatch.setattr(thinking, "_CACHE_PATH", cache_path)
    thinking.reset_for_tests()

    ai_response = "\n".join(
        [f"{i}. Фраза номер {i}…" for i in range(1, 41)]
    )

    async def fake_ai(prompt: str) -> str:
        assert "фраз" in prompt.lower()
        return ai_response

    await thinking.ensure_cached(fake_ai)

    # Cache file was written
    assert cache_path.exists()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert isinstance(data["phrases"], list)
    assert len(data["phrases"]) >= 40

    # Generated phrases are available; numbering stripped
    assert any("Фраза номер 1…" == p for p in data["phrases"])
    for p in data["phrases"]:
        assert not p[0].isdigit()


async def test_ensure_cached_reads_existing_cache_without_ai(monkeypatch, tmp_path):
    cache_path = tmp_path / "thinking.json"
    cached = [f"Cached phrase {i}…" for i in range(len(thinking._FALLBACK_PHRASES) + 5)]
    cache_path.write_text(
        json.dumps({"phrases": cached}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(thinking, "_CACHE_PATH", cache_path)
    thinking.reset_for_tests()

    called = False

    async def fake_ai(prompt: str) -> str:
        nonlocal called
        called = True
        return ""

    await thinking.ensure_cached(fake_ai)
    assert not called
    assert thinking.random_phrase() in cached


async def test_ensure_cached_keeps_fallback_when_ai_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(thinking, "_CACHE_PATH", tmp_path / "none.json")
    thinking.reset_for_tests()

    async def failing_ai(prompt: str) -> str:
        raise RuntimeError("boom")

    await thinking.ensure_cached(failing_ai)
    assert thinking.random_phrase() in thinking._FALLBACK_PHRASES


def test_sanitize_drops_garbage():
    cleaned = thinking._sanitize([
        "Думаю…",
        "",
        "  ",
        "a",  # too short
        "x" * 100,  # too long
        123,  # not str
        "Думаю…",  # duplicate
        '"Соображаю…"',  # quoted
    ])
    assert cleaned == ["Думаю…", "Соображаю…"]


def test_parse_ai_response_strips_numbering():
    raw = "1. Думаю…\n2) Соображаю…\n- Мозгую…\n   * Прикидываю…\n\n"
    result = thinking._parse_ai_response(raw)
    assert result == ["Думаю…", "Соображаю…", "Мозгую…", "Прикидываю…"]


def test_clean_contextual_normalises_trailing_dots():
    assert thinking._clean_contextual("Ищу твою карточку...") == "Ищу твою карточку…"
    assert thinking._clean_contextual("Мозгую.") == "Мозгую…"
    assert thinking._clean_contextual("Думаю…") == "Думаю…"


def test_clean_contextual_strips_quotes_and_markdown():
    assert thinking._clean_contextual('"Мозгую…"') == "Мозгую…"
    assert thinking._clean_contextual("*Мозгую…*") == "Мозгую…"
    assert thinking._clean_contextual("«Ищу карточку…»") == "Ищу карточку…"


def test_clean_contextual_rejects_out_of_range():
    assert thinking._clean_contextual("") is None
    assert thinking._clean_contextual("а") is None
    assert thinking._clean_contextual("Б" * 200) is None


def test_clean_contextual_uses_first_line():
    assert thinking._clean_contextual("Мозгую…\nпояснение модели") == "Мозгую…"


async def test_try_contextual_placeholder_returns_ai_phrase():
    thinking.reset_for_tests()

    async def fake(prompt: str) -> str:
        assert "скок см" in prompt
        return "Ищу твою карточку в поликлинике…"

    phrase = await thinking.try_contextual_placeholder(
        "скок см у меня пенис", fake
    )
    assert phrase == "Ищу твою карточку в поликлинике…"


async def test_try_contextual_placeholder_none_on_timeout():
    thinking.reset_for_tests()

    async def slow(prompt: str) -> str:
        import asyncio
        await asyncio.sleep(1.0)
        return "слишком поздно…"

    phrase = await thinking.try_contextual_placeholder(
        "вопрос", slow, timeout_sec=0.05
    )
    assert phrase is None


async def test_try_contextual_placeholder_none_on_error():
    thinking.reset_for_tests()

    async def broken(prompt: str) -> str:
        raise RuntimeError("nope")

    phrase = await thinking.try_contextual_placeholder("вопрос", broken)
    assert phrase is None


async def test_try_contextual_placeholder_none_on_empty_input():
    thinking.reset_for_tests()

    called = False

    async def should_not_be_called(prompt: str) -> str:
        nonlocal called
        called = True
        return ""

    phrase = await thinking.try_contextual_placeholder(
        "   ", should_not_be_called
    )
    assert phrase is None
    assert not called


async def test_contextual_placeholder_wrapper_falls_back_to_random():
    thinking.reset_for_tests()

    async def broken(prompt: str) -> str:
        raise RuntimeError("nope")

    phrase = await thinking.contextual_placeholder("вопрос", broken)
    assert phrase in thinking._FALLBACK_PHRASES
