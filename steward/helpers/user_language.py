"""Per-user language overrides for AI replies.

Stored in the DB as `repo.db.user_languages: dict[str, str]` (key — stringified
user_id, value — human-readable language name). Used as a joke/quirk: the
specified user gets the bot's answers in the chosen language regardless of the
user's prompt language. The hint is added as an extra system message and
reaches every AI handler that goes through `execute_ai_request_streaming` /
`execute_ai_request`.

Admin command `/lang` manages overrides at runtime.
"""

from __future__ import annotations

from steward.data.repository import Repository


def get_user_language(repo: Repository, user_id: int) -> str | None:
    return repo.db.user_languages.get(str(user_id))


def set_user_language(repo: Repository, user_id: int, language: str) -> None:
    repo.db.user_languages[str(user_id)] = language


def clear_user_language(repo: Repository, user_id: int) -> bool:
    return repo.db.user_languages.pop(str(user_id), None) is not None


def language_prompt_for(repo: Repository, user_id: int) -> str | None:
    language = get_user_language(repo, user_id)
    if not language:
        return None
    return (
        f"ВАЖНО: пользователю отвечай ТОЛЬКО на {language} языке, "
        "независимо от того, на каком языке он сам пишет. "
        "Это его языковое предпочтение в этом чате."
    )
