import asyncio
from time import time
from unittest.mock import MagicMock

import pytest

from steward.data.models.user_fact import UserFact
from steward.helpers import user_memory


@pytest.fixture
def repo():
    repo = MagicMock()
    repo.db.user_facts = []
    return repo


def test_add_facts_stores_and_dedupes(repo):
    added = user_memory.add_facts(repo, 100, ["Любит рок", "любит рок  ", "Играет на гитаре"])
    assert len(added) == 2
    assert [f.text for f in added] == ["Любит рок", "Играет на гитаре"]
    # second call with same first fact should not duplicate
    again = user_memory.add_facts(repo, 100, ["Любит рок"])
    assert again == []


def test_add_facts_trims_long(repo):
    long = "x" * 300
    added = user_memory.add_facts(repo, 1, [long])
    assert len(added) == 1
    assert len(added[0].text) <= user_memory.MAX_FACT_LENGTH


def test_add_facts_caps_per_user(repo):
    # seed with cap already
    now = time()
    repo.db.user_facts.extend(
        UserFact(user_id=7, text=f"старый факт {i}", created_at=now - i)
        for i in range(user_memory.MAX_FACTS_PER_USER)
    )
    added = user_memory.add_facts(repo, 7, ["новый факт"])
    assert len(added) == 1
    remaining = [f for f in repo.db.user_facts if f.user_id == 7]
    assert len(remaining) == user_memory.MAX_FACTS_PER_USER
    # newest should survive, oldest should be evicted
    assert any(f.text == "новый факт" for f in remaining)
    oldest_seed_text = f"старый факт {user_memory.MAX_FACTS_PER_USER - 1}"
    assert not any(f.text == oldest_seed_text for f in remaining)


def test_get_recent_facts_filters_and_sorts(repo, monkeypatch):
    monkeypatch.setenv("USER_MEMORY_TTL_HOURS", "1")
    now = time()
    repo.db.user_facts.extend([
        UserFact(user_id=1, text="старое", created_at=now - 7200),  # 2h ago, expired
        UserFact(user_id=1, text="свежее A", created_at=now - 30),
        UserFact(user_id=1, text="свежее B", created_at=now - 10),
        UserFact(user_id=2, text="чужое", created_at=now - 1),
    ])
    facts = user_memory.get_recent_facts(repo, user_id=1)
    assert facts == ["свежее B", "свежее A"]


def test_prune_expired_removes_old(repo, monkeypatch):
    monkeypatch.setenv("USER_MEMORY_TTL_HOURS", "1")
    now = time()
    repo.db.user_facts.extend([
        UserFact(user_id=1, text="живое", created_at=now - 10),
        UserFact(user_id=1, text="сдохло", created_at=now - 10_000),
    ])
    removed = user_memory.prune_expired(repo, now=now)
    assert removed == 1
    texts = [f.text for f in repo.db.user_facts]
    assert texts == ["живое"]


def test_ttl_seconds_respects_env(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_TTL_HOURS", "6")
    assert user_memory.ttl_seconds() == 6 * 3600
    monkeypatch.setenv("USER_MEMORY_TTL_HOURS", "garbage")
    assert user_memory.ttl_seconds() == 24 * 3600


def test_format_facts_for_prompt_empty_returns_empty():
    assert user_memory.format_facts_for_prompt(1, "Vasya", []) == ""


def test_format_facts_for_prompt_renders():
    rendered = user_memory.format_facts_for_prompt(1, "Вася", ["Любит рок", "28 лет"])
    assert "Вася" in rendered
    assert "- Любит рок" in rendered
    assert "- 28 лет" in rendered
    assert "используй" in rendered.lower()


def test_parse_facts_strips_markers():
    out = user_memory._parse_facts(
        "1. Любит рок\n"
        "- 28 лет\n"
        '  "Играет на гитаре"\n'
        "\n"
        "* Работает фронтендером\n"
    )
    assert out == [
        "Любит рок",
        "28 лет",
        "Играет на гитаре",
        "Работает фронтендером",
    ]


async def test_extract_facts_via_ai_parses_response():
    async def fake(prompt: str) -> str:
        assert "Сообщение пользователя" in prompt
        return "Сегодня день рождения, 28 лет\nРаботает фронтендером"

    facts = await user_memory.extract_facts_via_ai("др у меня сегодня, 28 стукнуло, фронтендер", fake)
    assert facts == ["Сегодня день рождения, 28 лет", "Работает фронтендером"]


async def test_extract_facts_via_ai_returns_empty_on_timeout():
    async def slow(prompt: str) -> str:
        await asyncio.sleep(1.0)
        return "Что-то"

    facts = await user_memory.extract_facts_via_ai("msg", slow, timeout_sec=0.05)
    assert facts == []


async def test_extract_facts_via_ai_returns_empty_on_error():
    async def broken(prompt: str) -> str:
        raise RuntimeError("nope")

    facts = await user_memory.extract_facts_via_ai("msg", broken)
    assert facts == []


async def test_extract_facts_via_ai_empty_on_empty_input():
    called = False

    async def never(prompt: str) -> str:
        nonlocal called
        called = True
        return ""

    facts = await user_memory.extract_facts_via_ai("  ", never)
    assert facts == []
    assert not called


# --- passive collector funnel ---------------------------------------------


def test_should_consider_skips_short(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_COLLECT_MIN_LEN", "15")
    assert not user_memory.should_consider_message("я")
    assert not user_memory.should_consider_message("")
    assert not user_memory.should_consider_message("   ")


def test_should_consider_skips_commands(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_COLLECT_MIN_LEN", "5")
    assert not user_memory.should_consider_message("/help что-нибудь")


def test_should_consider_skips_without_signal(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_COLLECT_MIN_LEN", "5")
    # длинное, на русском, но без первого лица — мимо
    assert not user_memory.should_consider_message("погода сегодня отличная, солнце светит")


def test_should_consider_skips_non_cyrillic(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_COLLECT_MIN_LEN", "5")
    # first-person signal в латинице не ловим
    assert not user_memory.should_consider_message("I love rock music so much")


def test_should_consider_passes_on_signal(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_COLLECT_MIN_LEN", "5")
    assert user_memory.should_consider_message("я живу в Минске уже лет десять")
    assert user_memory.should_consider_message("у меня сегодня днюха ребята")
    assert user_memory.should_consider_message("я работаю фронтендером")


def test_has_personal_signal_whole_word():
    # "моя" должно ловиться как слово, но не как часть "моя" в слове "помоя"
    assert user_memory.has_personal_signal("моя собака лучшая")
    assert not user_memory.has_personal_signal("сомоя")


def test_collector_batches_after_threshold(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_COLLECT_MIN_LEN", "5")
    monkeypatch.setenv("USER_MEMORY_COLLECT_BATCH_SIZE", "3")
    monkeypatch.setenv("USER_MEMORY_COLLECT_COOLDOWN_SEC", "0")
    c = user_memory.ChatMemoryCollector()

    assert c.observe(1, "я живу в Минске 10 лет") is None
    assert c.observe(1, "не сигнал") is None
    assert c.observe(1, "я работаю фронтендером") is None
    batch = c.observe(1, "у меня есть собака")
    assert batch == [
        "я живу в Минске 10 лет",
        "я работаю фронтендером",
        "у меня есть собака",
    ]


def test_collector_respects_cooldown(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_COLLECT_MIN_LEN", "5")
    monkeypatch.setenv("USER_MEMORY_COLLECT_BATCH_SIZE", "2")
    monkeypatch.setenv("USER_MEMORY_COLLECT_COOLDOWN_SEC", "9999")
    c = user_memory.ChatMemoryCollector()

    c.observe(1, "я живу в Минске")
    first_batch = c.observe(1, "я работаю тут же")
    assert first_batch is not None  # threshold reached

    # сразу же ещё: cooldown не даёт запустить второй extract
    c.observe(1, "у меня уже все горит")
    assert c.observe(1, "я читаю книгу") is None


def test_collector_disabled_via_env(monkeypatch):
    monkeypatch.setenv("USER_MEMORY_COLLECT_FROM_CHAT", "false")
    monkeypatch.setenv("USER_MEMORY_COLLECT_BATCH_SIZE", "1")
    c = user_memory.ChatMemoryCollector()
    assert c.observe(1, "я живу где-то") is None


async def test_extract_facts_batch_via_ai_parses_response():
    async def fake(prompt: str) -> str:
        assert "ОДНОГО пользователя" in prompt
        return "Живёт в Минске\nРаботает фронтендером"

    facts = await user_memory.extract_facts_batch_via_ai(
        ["я живу в минске", "я работаю фронтендером"], fake
    )
    assert facts == ["Живёт в Минске", "Работает фронтендером"]


async def test_extract_facts_batch_via_ai_empty_input():
    called = False

    async def never(prompt: str) -> str:
        nonlocal called
        called = True
        return ""

    assert await user_memory.extract_facts_batch_via_ai([], never) == []
    assert await user_memory.extract_facts_batch_via_ai(["  "], never) == []
    assert not called
