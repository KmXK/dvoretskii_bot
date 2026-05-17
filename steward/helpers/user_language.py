"""Per-user language overrides for AI replies.

Used as a joke/quirk: a specific user gets the bot's answers in a chosen
language regardless of the user's prompt language. The hint is added as an
extra system message and reaches every AI handler that goes through
`execute_ai_request_streaming` / `execute_ai_request`.
"""

# user_id → human-readable language name (нужно для системного промпта)
USER_LANGUAGE_OVERRIDES: dict[int, str] = {
    430123749: "украинский",  # Юра
}


def language_prompt_for(user_id: int) -> str | None:
    language = USER_LANGUAGE_OVERRIDES.get(user_id)
    if not language:
        return None
    return (
        f"ВАЖНО: пользователю отвечай ТОЛЬКО на {language} языке, "
        "независимо от того, на каком языке он сам пишет. "
        "Это его языковое предпочтение в этом чате."
    )
