"""Enrich news text with Grok-online and generate anchor script with image queries."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from steward.helpers.ai import OpenRouterModel, make_openrouter_query

logger = logging.getLogger(__name__)


EMOTIONS = (
    "neutral",      # default / explanatory
    "happy",        # good news, positive announcement
    "serious",      # weighty, important news
    "surprised",    # unexpected fact
    "thoughtful",   # analysis, "вот в чём суть"
    "smirk",        # sarcastic / ironic, the punchline
    "shocked",      # WTF moment
    "concerned",    # warning, problem
    "amused",       # mild joke, fun fact
    "skeptical",    # doubt, "ну-ну"
)


@dataclass
class Slide:
    text: str
    image_query: str
    is_meme: bool = False
    emotion: str = "neutral"


@dataclass
class Script:
    slides: list[Slide]

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.slides)


_ENRICH_PROMPT = """\
Ты редактор новостей. Тебе дан текст пользователя. Найди в актуальных интернет-источниках
дополнительные факты, контекст и подробности по теме. Если конкретики мало — добавь общий
бэкграунд (история вопроса, типичные позиции сторон, статистика).

Верни строго JSON:
{{
  "topic": "короткий заголовок темы (3-6 слов)",
  "facts": ["факт 1", "факт 2", ...],
  "tone": "neutral|funny|sarcastic"
}}

5-8 фактов, каждый одно-два коротких предложения. Без markdown, без объяснений вне JSON.

Текст пользователя:
{text}
"""


_SCRIPT_PROMPT = """\
Ты сценарист короткой новостной подачи в стиле TikTok. На основе темы и фактов сделай
сценарий для диктора-мужчины с грубоватым голосом на ~30-40 секунд (70-90 слов всего).

Разбей на ровно 5 коротких реплик (слайдов). Для каждой:
- "text": 1-2 предложения по-русски, разговорный, мужской диктор, с лёгким сарказмом или
  иронией там где уместно. Без эмодзи.
- "image_query": 2-4 английских слова, простые, для поиска иллюстрации в Google Images.
  Для мемов — известные шаблоны ("drake meme", "distracted boyfriend meme", "doge").
- "is_meme": true только если эта реплика — явная шутка с мем-подачей. Максимум 1-2 из 5.
- "emotion": эмоция диктора на этой реплике, ровно одна из:
  neutral (нейтрально/пояснение)
  happy (хорошая новость)
  serious (важное, веское)
  surprised (неожиданный факт)
  thoughtful (размышление, "вот в чём суть")
  smirk (сарказм/ирония, панчлайн)
  shocked (WTF-момент)
  concerned (предупреждение, проблема)
  amused (мягкая шутка)
  skeptical (сомнение, "ну-ну")
  Выбирай эмоцию ПОД СОДЕРЖАНИЕ реплики. Разнообразь — не ставь одну и ту же эмоцию подряд.

Структура: первый слайд = вступление (часто serious или neutral), последний = панчлайн (часто smirk/amused/skeptical).

Верни строго JSON:
{{
  "slides": [
    {{"text": "...", "image_query": "...", "is_meme": false, "emotion": "neutral"}},
    ...
  ]
}}

Тема: {topic}
Тон: {tone}
Факты:
{facts}
"""


def _extract_json(s: str) -> dict:
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON in model output: {s[:300]}")
    return json.loads(m.group(0))


async def enrich(user_id: int, text: str) -> dict:
    raw = await make_openrouter_query(
        user_id,
        OpenRouterModel.GROK_4_FAST_ONLINE,
        [("user", _ENRICH_PROMPT.format(text=text))],
        timeout_seconds=90.0,
    )
    data = _extract_json(raw)
    logger.info("news enrich: topic=%r facts=%d", data.get("topic"), len(data.get("facts", [])))
    return data


async def make_script(user_id: int, enrich_data: dict) -> Script:
    facts_str = "\n".join(f"- {f}" for f in enrich_data.get("facts", []))
    prompt = _SCRIPT_PROMPT.format(
        topic=enrich_data.get("topic", ""),
        tone=enrich_data.get("tone", "neutral"),
        facts=facts_str,
    )
    raw = await make_openrouter_query(
        user_id,
        OpenRouterModel.GROK_4_FAST_ONLINE,
        [("user", prompt)],
        timeout_seconds=90.0,
    )
    data = _extract_json(raw)
    slides = [
        Slide(
            text=s["text"],
            image_query=s["image_query"],
            is_meme=bool(s.get("is_meme", False)),
            emotion=s["emotion"] if s.get("emotion") in EMOTIONS else "neutral",
        )
        for s in data.get("slides", [])
        if s.get("text") and s.get("image_query")
    ]
    return Script(slides=slides)
