"""Per-user short-term "memory" — small list of facts a bot keeps about each
user for a configurable TTL (default 24 hours). Facts are extracted from the
user's own messages by a cheap model and injected into the system prompt of
subsequent AI requests.

Design goals:
- Cheap on the hot path: adding to the prompt costs at most ~0.5K tokens
  because of the hard per-user cap.
- No vectors, no external store — just the existing db.json via collections.
- Fail-quietly: AI extraction errors or timeouts never block the main reply.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from inspect import isawaitable
from time import time
from typing import Awaitable, Callable

from steward.data.models.user_fact import UserFact
from steward.data.repository import Repository

logger = logging.getLogger(__name__)

MAX_FACTS_PER_USER = 20
MAX_FACT_LENGTH = 120

# --- Passive collector from chat messages ---------------------------------
# Tuned to keep the cost near zero: most messages never reach the AI because
# they're too short, don't contain first-person signals, or fall inside a
# per-user cooldown window.
_COLLECT_MIN_LEN_DEFAULT = 15
_COLLECT_BATCH_SIZE_DEFAULT = 5
_COLLECT_BUFFER_CAP = 20
_COLLECT_COOLDOWN_SEC_DEFAULT = 30 * 60

# Russian first-person signal words — lowercased, matched as whole words.
_SIGNAL_WORDS = (
    "я", "мне", "меня", "мной", "мною", "мой", "моя", "моё", "моё", "мои",
    "моего", "моей", "моих", "моим", "моими", "у меня", "от меня", "про меня",
    "живу", "работаю", "учусь", "родился", "родилась", "переехал", "переехала",
    "женат", "замужем", "влюбился", "влюбилась", "болею", "увлекаюсь", "люблю",
    "ненавижу", "езжу", "играю", "пишу", "читаю",
)
_SIGNAL_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(w) for w in _SIGNAL_WORDS) + r")(?!\w)",
    re.IGNORECASE,
)


def ttl_seconds() -> int:
    """Fact TTL, configurable via USER_MEMORY_TTL_HOURS (default 24 hours)."""
    raw = os.environ.get("USER_MEMORY_TTL_HOURS", "24")
    try:
        hours = float(raw)
    except ValueError:
        return 24 * 3600
    return max(0, int(hours * 3600))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def prune_expired(repo: Repository, now: float | None = None) -> int:
    """Drop facts older than TTL. Returns number removed."""
    ttl = ttl_seconds()
    if ttl <= 0:
        return 0
    now = now if now is not None else time()
    cutoff = now - ttl
    facts = repo.db.user_facts
    fresh = [f for f in facts if f.created_at >= cutoff]
    removed = len(facts) - len(fresh)
    if removed:
        facts.clear()
        facts.extend(fresh)
    return removed


def get_recent_facts(repo: Repository, user_id: int) -> list[str]:
    """Return active fact texts for a user, newest first, capped at
    MAX_FACTS_PER_USER."""
    ttl = ttl_seconds()
    if ttl <= 0:
        return []
    cutoff = time() - ttl
    facts = [
        f
        for f in repo.db.user_facts
        if f.user_id == user_id and f.created_at >= cutoff
    ]
    facts.sort(key=lambda f: f.created_at, reverse=True)
    return [f.text for f in facts[:MAX_FACTS_PER_USER]]


def add_facts(repo: Repository, user_id: int, texts: list[str]) -> list[UserFact]:
    """Append new facts to the user's memory, deduping against existing ones
    and trimming the oldest if over the cap. Returns the facts actually added."""
    if not texts:
        return []

    now = time()
    existing = {
        _normalize(f.text)
        for f in repo.db.user_facts
        if f.user_id == user_id
    }

    added: list[UserFact] = []
    for raw in texts:
        text = raw.strip()
        if not text:
            continue
        if len(text) > MAX_FACT_LENGTH:
            text = text[: MAX_FACT_LENGTH - 1].rstrip() + "…"
        key = _normalize(text)
        if not key or key in existing:
            continue
        existing.add(key)
        fact = UserFact(user_id=user_id, text=text, created_at=now)
        repo.db.user_facts.append(fact)
        added.append(fact)

    # Enforce per-user cap (keep the newest).
    user_facts = [f for f in repo.db.user_facts if f.user_id == user_id]
    if len(user_facts) > MAX_FACTS_PER_USER:
        user_facts.sort(key=lambda f: f.created_at)
        overflow = user_facts[: len(user_facts) - MAX_FACTS_PER_USER]
        overflow_ids = {id(f) for f in overflow}
        repo.db.user_facts[:] = [
            f for f in repo.db.user_facts if id(f) not in overflow_ids
        ]

    return added


_EXTRACT_PROMPT = (
    "Проанализируй сообщение пользователя и извлеки КОРОТКИЕ факты ПРО НЕГО "
    "САМОГО (предпочтения, состояние, планы, биография, контекст, события). "
    "Игнорируй общие вопросы к боту, команды, мнения о третьих лицах.\n\n"
    "Каждый факт — одно предложение, 2–12 слов, на русском, написано от "
    "третьего лица в настоящем времени. Не цитируй сообщение дословно, "
    "перефразируй. Не выдумывай, не экстраполируй.\n\n"
    "Если ничего личного нет — выдай пустую строку.\n\n"
    "Примеры:\n"
    '- "сегодня днюха, мне 28 стукнуло" → "Сегодня день рождения, 28 лет"\n'
    '- "я фронтендер, пишу на реакте" → "Работает фронтендером, пишет на React"\n'
    '- "люблю рок, особенно alice in chains" → "Слушает рок, любит Alice in Chains"\n'
    '- "сколько км до марса?" → (пусто)\n\n'
    "Выдай только список фактов, по одной на строку, без номеров, "
    "без кавычек, без вводного текста.\n\n"
    "Сообщение пользователя: {message}"
)

_EXTRACT_TIMEOUT_SEC = 4.0
_EXTRACT_MESSAGE_CUTOFF = 600


_LINE_MARKER_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s+")


def _parse_facts(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        line = _LINE_MARKER_RE.sub("", line, count=1).strip()
        for ch in ('"', "'", "«", "»"):
            line = line.strip(ch).strip()
        if not line:
            continue
        if len(line) < 3 or len(line) > MAX_FACT_LENGTH:
            continue
        out.append(line)
    return out


async def extract_facts_via_ai(
    user_message: str,
    quick_call: Callable[[str], str | Awaitable[str]],
    *,
    timeout_sec: float = _EXTRACT_TIMEOUT_SEC,
) -> list[str]:
    """Ask a cheap model to pull facts out of a user message. Returns an empty
    list on timeout, error, or if the model produced nothing usable."""
    message = user_message.strip()[:_EXTRACT_MESSAGE_CUTOFF]
    if not message:
        return []

    prompt = _EXTRACT_PROMPT.format(message=message)

    async def _run() -> list[str]:
        result = quick_call(prompt)
        if isawaitable(result):
            result = await result
        if not isinstance(result, str):
            return []
        return _parse_facts(result)

    try:
        return await asyncio.wait_for(_run(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        return []
    except Exception as e:
        logger.debug("fact extraction failed: %s", e)
        return []


def format_facts_for_prompt(user_id: int, user_name: str | None, facts: list[str]) -> str:
    """Render facts as a system-prompt block. Returns empty string if no facts."""
    if not facts:
        return ""
    subject = user_name.strip() if user_name else f"пользователя #{user_id}"
    bullets = "\n".join(f"- {f}" for f in facts)
    return (
        f"Личный контекст про {subject} (используй при ответе, если уместно):\n{bullets}"
    )


# --- passive collector ----------------------------------------------------


def _collect_enabled() -> bool:
    raw = os.environ.get("USER_MEMORY_COLLECT_FROM_CHAT", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _collect_min_len() -> int:
    return _env_int("USER_MEMORY_COLLECT_MIN_LEN", _COLLECT_MIN_LEN_DEFAULT)


def _collect_batch_size() -> int:
    return _env_int("USER_MEMORY_COLLECT_BATCH_SIZE", _COLLECT_BATCH_SIZE_DEFAULT)


def _collect_cooldown_sec() -> int:
    return _env_int("USER_MEMORY_COLLECT_COOLDOWN_SEC", _COLLECT_COOLDOWN_SEC_DEFAULT)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def has_personal_signal(text: str) -> bool:
    """Fast heuristic: does the text contain a first-person marker word?"""
    return bool(_SIGNAL_RE.search(text))


def should_consider_message(text: str) -> bool:
    """Cheap pre-filter before we even think about batching or AI calls."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("/"):  # bot command
        return False
    if len(stripped) < _collect_min_len():
        return False
    # Require at least one cyrillic letter — facts are in Russian.
    if not re.search(r"[А-Яа-яЁё]", stripped):
        return False
    return has_personal_signal(stripped)


_BATCH_EXTRACT_PROMPT = (
    "Ниже несколько сообщений ОДНОГО пользователя из группового чата. "
    "Извлеки короткие факты ПРО НЕГО САМОГО (предпочтения, состояние, планы, "
    "биография, контекст, события). Игнорируй общие шутки, мемы, реакции, "
    "упоминания третьих лиц.\n\n"
    "Каждый факт — одно предложение, 2–12 слов, на русском, от третьего лица, "
    "в настоящем времени. Перефразируй, не цитируй. Не выдумывай.\n\n"
    "Если ничего личного нет — выдай пустую строку.\n\n"
    "Сообщения пользователя:\n{messages}\n\n"
    "Выдай только список фактов, по одной на строку, без номеров, без кавычек, "
    "без вводного текста."
)


async def extract_facts_batch_via_ai(
    messages: list[str],
    quick_call: Callable[[str], str | Awaitable[str]],
    *,
    timeout_sec: float = _EXTRACT_TIMEOUT_SEC,
) -> list[str]:
    """Batch version of extract_facts_via_ai: one AI call over many messages."""
    cleaned = [m.strip() for m in messages if m and m.strip()]
    if not cleaned:
        return []
    joined = "\n".join(f"- {m}" for m in cleaned)[: _EXTRACT_MESSAGE_CUTOFF * 4]
    prompt = _BATCH_EXTRACT_PROMPT.format(messages=joined)

    async def _run() -> list[str]:
        result = quick_call(prompt)
        if isawaitable(result):
            result = await result
        if not isinstance(result, str):
            return []
        return _parse_facts(result)

    try:
        return await asyncio.wait_for(_run(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        return []
    except Exception as e:
        logger.debug("batch fact extraction failed: %s", e)
        return []


class ChatMemoryCollector:
    """In-memory buffer per user. Flushes into an AI batch-extract call when
    the user has accumulated enough signal-bearing messages AND the cooldown
    since the last extract has elapsed.

    State is process-local and ephemeral: losing it on restart is fine — we
    only lose a few in-flight messages, not persisted facts.
    """

    def __init__(self) -> None:
        self._buffers: dict[int, list[str]] = {}
        self._last_extract: dict[int, float] = {}

    def _drop_buffer(self, user_id: int) -> None:
        self._buffers.pop(user_id, None)

    def observe(self, user_id: int, text: str) -> list[str] | None:
        """Record a message. Returns a batch ready for extraction if the user
        tripped the threshold + cooldown; otherwise None."""
        if not _collect_enabled():
            return None
        if not should_consider_message(text):
            return None

        buf = self._buffers.setdefault(user_id, [])
        buf.append(text.strip())
        if len(buf) > _COLLECT_BUFFER_CAP:
            del buf[: len(buf) - _COLLECT_BUFFER_CAP]

        if len(buf) < _collect_batch_size():
            return None

        now = time()
        cooldown = _collect_cooldown_sec()
        last = self._last_extract.get(user_id, 0.0)
        if cooldown > 0 and now - last < cooldown:
            return None

        batch = list(buf)
        self._buffers[user_id] = []
        self._last_extract[user_id] = now
        return batch

    def reset_for_tests(self) -> None:
        self._buffers.clear()
        self._last_extract.clear()


chat_memory_collector = ChatMemoryCollector()
