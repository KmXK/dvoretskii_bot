from typing import AsyncIterator, ClassVar

from steward.features._persona import AiPersonaFeature
from steward.helpers.ai import (
    DIANA_PROMPT,
    OpenRouterModel,
    make_openrouter_query,
    make_openrouter_stream,
)
from steward.helpers.limiter import Duration


_GROK = OpenRouterModel.GROK_4_FAST


class DianaFeature(AiPersonaFeature):
    command = "diana"
    description = "Поболтать с Дианой по душам (18+)"
    help_examples = [
        "/diana — начать разговор",
        "/diana привет — одна реплика",
        "диана, что думаешь? — обращение прямо в чате",
    ]

    persona_name: ClassVar[str] = "diana"
    aliases_in_chat: ClassVar[tuple[str, ...]] = ("грязная диана", "диана")
    greeting: ClassVar[str | None] = "Алло… слушаю тебя."
    allowed_chats_key: ClassVar[str | None] = "diana_allowed_chats"
    rate_limit: ClassVar[int] = 5
    rate_window: ClassVar[int] = 20 * Duration.SECOND
    denied_message: ClassVar[str] = (
        "Диана работает только тет-а-тет или в чате, где админ её разрешил."
    )
    rate_limited_message: ClassVar[str] = "Тише, тише. Дай мне отдышаться."
    private_allow_message: ClassVar[str] = "В личке Диана и так всегда с тобой."
    allow_on_message: ClassVar[str] = "Диана теперь доступна всем в этом чате."
    allow_off_message: ClassVar[str] = "Диана больше не работает в этом чате."

    async def _call(self, user_id: int, messages: list[tuple[str, str]]) -> str:
        return await make_openrouter_query(user_id, _GROK, messages, DIANA_PROMPT)

    async def _stream(
        self, user_id: int, messages: list[tuple[str, str]]
    ) -> AsyncIterator[str]:
        return await make_openrouter_stream(user_id, _GROK, messages, DIANA_PROMPT)
