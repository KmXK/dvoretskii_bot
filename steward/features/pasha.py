from typing import AsyncIterator, ClassVar

from steward.features._persona import AiPersonaFeature
from steward.helpers.ai import (
    PASHA_PROMPT,
    OpenRouterModel,
    make_openrouter_query,
    make_openrouter_stream,
)
from steward.helpers.limiter import Duration


_GROK = OpenRouterModel.GROK_4_FAST


class PashaFeature(AiPersonaFeature):
    command = "pasha"
    description = "Диалог с Пашей"
    help_examples = [
        "/pasha — позвать Пашу",
        "/pasha как дела? — одна реплика",
        "пашок, что думаешь? — обращение прямо в чате",
    ]

    persona_name: ClassVar[str] = "pasha"
    aliases_in_chat: ClassVar[tuple[str, ...]] = ("пашок", "пп")
    greeting: ClassVar[str | None] = "Слушаю..."
    rate_limit: ClassVar[int] = 7
    rate_window: ClassVar[int] = 20 * Duration.SECOND

    async def _call(self, user_id: int, messages: list[tuple[str, str]]) -> str:
        return await make_openrouter_query(user_id, _GROK, messages, PASHA_PROMPT)

    async def _stream(
        self, user_id: int, messages: list[tuple[str, str]]
    ) -> AsyncIterator[str]:
        return await make_openrouter_stream(user_id, _GROK, messages, PASHA_PROMPT)
