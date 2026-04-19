"""Whimsical placeholder phrases for streaming replies.

`random_phrase()` returns one of a pool of short "I'm thinking…" lines. The
pool starts with a small built-in fallback and is expanded at runtime: when
`ensure_cached()` is called (typically from an AI feature's @on_init), it asks
the AI to generate a bigger list and stores it in `data/thinking_phrases.json`.
Subsequent starts read from the cache without touching the AI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from inspect import isawaitable
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("data/thinking_phrases.json")
_MIN_PHRASE_LEN = 3
_MAX_PHRASE_LEN = 40
_TARGET_COUNT = 40

_FALLBACK_PHRASES: tuple[str, ...] = (
    # нейтральные
    "Думаю…",
    "Соображаю…",
    "Размышляю…",
    "Формулирую…",
    "Вспоминаю…",
    "Вникаю…",
    # разговорные / с юмором
    "Мозгую…",
    "Обмозговываю…",
    "Шевелю извилинами…",
    "Копаюсь в голове…",
    "Мысли разбрелись, собираю…",
    "Гоняю мысли по кругу…",
    "Прикидываю хер к носу…",
    "Лезу в архивы…",
    # пацанские / дворовые
    "Бля, щас подумаю…",
    "Погоди, братан, въезжаю…",
    "Сек, соображалка греется…",
    "Кумекаю, как сказать…",
    "Хз пока, но ща будет…",
    # слегка вульгарные / дерзкие
    "Чё ответить, ебана…",
    "Напрягаю мозги, сука…",
    "Нихуя не просто, но щас…",
    "Башка кипит, щас выдам…",
    "Чё за дичь ты спросил, щас…",
    # нелепые / абсурдные
    "Спрашиваю у внутреннего дворецкого…",
    "Подкидываю монетку…",
    "Гадаю на кофейной гуще…",
    "Жду озарения…",
    "Заряжаю нейроны…",
    "Сверяюсь со звёздами…",
)

_GENERATE_PROMPT = (
    f"Сгенерируй {_TARGET_COUNT} коротких фраз на русском, описывающих процесс "
    "обдумывания ответа ботом в реальном времени. Каждая фраза — 1–6 слов с "
    "троеточием в конце.\n"
    "Разнообразие стилей обязательно, примерно поровну:\n"
    '- нейтральные ("Думаю…", "Соображаю…")\n'
    '- разговорные с юмором ("Мозгую…", "Шевелю извилинами…")\n'
    '- пацанские/дворовые ("Погоди, братан, въезжаю…", "Сек, соображалка греется…")\n'
    '- дерзкие, можно с лёгкой вульгарностью и матом ("Напрягаю мозги, сука…", '
    '"Нихуя не просто, но щас…")\n'
    '- нелепые/абсурдные ("Подкидываю монетку…", "Жду озарения…")\n'
    "Никакой политики, никакой жести, никакой дискриминации. Бот общается в кругу "
    "друзей, так что раскованно, но без перехода черты.\n"
    "Выдай только список фраз, по одной на строку, без номеров, без кавычек, без "
    "вводного и заключительного текста."
)


_phrases: list[str] = list(_FALLBACK_PHRASES)


def _load_cache() -> list[str] | None:
    try:
        raw = _CACHE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("thinking phrases: cannot read cache: %s", e)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("thinking phrases: bad cache json: %s", e)
        return None
    phrases = data.get("phrases")
    if not isinstance(phrases, list):
        return None
    cleaned = _sanitize(phrases)
    return cleaned or None


def _save_cache(phrases: list[str]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps({"phrases": phrases}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("thinking phrases: cannot write cache: %s", e)


def _sanitize(candidates: list) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, str):
            continue
        s = item.strip().strip('"').strip("'").strip("-").strip()
        if not s or s in seen:
            continue
        if not (_MIN_PHRASE_LEN <= len(s) <= _MAX_PHRASE_LEN):
            continue
        seen.add(s)
        out.append(s)
    return out


def _parse_ai_response(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    cleaned: list[str] = []
    for ln in lines:
        while ln and ln[0] in "-*•0123456789.) ":
            ln = ln[1:].strip()
        if ln:
            cleaned.append(ln)
    return _sanitize(cleaned)


def random_phrase() -> str:
    return random.choice(_phrases) if _phrases else _FALLBACK_PHRASES[0]


async def ensure_cached(
    ai_call: Callable[[str], str | Awaitable[str]] | None = None,
) -> None:
    """Load the pool from disk; if empty and `ai_call` given, generate once.

    `ai_call` receives the prompt and returns (or awaits) the full text of the
    AI response. It's expected to be idempotent — it's invoked at most once per
    process.
    """
    global _phrases

    cached = _load_cache()
    if cached and len(cached) >= len(_FALLBACK_PHRASES):
        _phrases = cached
        return

    if ai_call is None:
        return

    try:
        result = ai_call(_GENERATE_PROMPT)
        if isawaitable(result):
            result = await result
    except Exception as e:
        logger.warning("thinking phrases: AI generation failed: %s", e)
        return

    if not isinstance(result, str):
        return

    generated = _parse_ai_response(result)
    if len(generated) < len(_FALLBACK_PHRASES):
        logger.info(
            "thinking phrases: AI returned only %d valid lines, keeping fallback",
            len(generated),
        )
        return

    # Merge with fallback so we always have reliable baseline phrases too.
    merged: list[str] = []
    seen: set[str] = set()
    for s in [*generated, *_FALLBACK_PHRASES]:
        if s not in seen:
            seen.add(s)
            merged.append(s)
    _phrases = merged
    _save_cache(_phrases)
    logger.info("thinking phrases: cached %d phrases", len(_phrases))


def reset_for_tests() -> None:
    """Reset the in-memory pool. Intended for tests only."""
    global _phrases
    _phrases = list(_FALLBACK_PHRASES)
