from typing import AsyncIterator, ClassVar

from telegram import Message

from steward.features._persona import AiPersonaFeature
from steward.helpers.ai import (
    PASHA_PROMPT,
    make_yandex_ai_query,
    make_yandex_ai_stream,
)
from steward.helpers.limiter import Duration


_YANDEX_DENIAL = "Я не могу обсуждать эту тему."
_DENIAL_REPLACEMENT = "Ой, иди нахуй"


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
        return await make_yandex_ai_query(user_id, messages, PASHA_PROMPT)

    async def _stream(
        self, user_id: int, messages: list[tuple[str, str]]
    ) -> AsyncIterator[str]:
        return await make_yandex_ai_stream(user_id, messages, PASHA_PROMPT)

    async def _post_process(self, bot_message: Message, full_text: str) -> None:
        if _YANDEX_DENIAL not in full_text:
            return
        try:
            await bot_message.edit_text(_DENIAL_REPLACEMENT)
        except Exception:
            pass
