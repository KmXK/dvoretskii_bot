import logging
from typing import Any

from steward.data.repository import Repository
from steward.helpers.curse_debt import accrue_curse_debt, today_msk
from steward.helpers.curse_detector import CurseDetector
from steward.metrics.base import ContextMetrics, Labels


logger = logging.getLogger(__name__)

CURSE_REACTION = "🤬"
_DETECTOR = CurseDetector()


def _metric_user_name(user: Any, user_id: int) -> str:
    username = getattr(user, "username", None)
    if username:
        return str(username)
    first_name = getattr(user, "first_name", None)
    if first_name:
        return str(first_name)
    return str(user_id)


def _message_chat_id(message: Any) -> int | None:
    chat_id = getattr(message, "chat_id", None)
    if isinstance(chat_id, int):
        return chat_id
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    return chat_id if isinstance(chat_id, int) else None


async def process_curse_text(
    repo: Repository,
    metrics: ContextMetrics,
    *,
    user_id: int,
    text: str | None,
    source_message: Any | None = None,
    metric_labels: Labels | None = None,
) -> int:
    if not text:
        return 0

    words = set(repo.db.curse_words)
    if not words:
        return 0

    count = _DETECTOR.count(
        text,
        words,
        set(repo.db.curse_ignore_words),
    )
    if count <= 0:
        return 0

    if metric_labels is None:
        metrics.inc("bot_curse_words_total", value=count)
    else:
        metrics.inc("bot_curse_words_total", metric_labels, value=count)

    if source_message is not None:
        try:
            await source_message.set_reaction(CURSE_REACTION)
        except Exception:
            logger.warning("failed to set curse reaction", exc_info=True)

    if accrue_curse_debt(repo, user_id, count, today_msk()):
        await repo.save()
    return count


async def process_transcribed_curse_text(
    repo: Repository,
    metrics: ContextMetrics,
    *,
    source_message: Any | None,
    text: str | None,
    capability_cls: type,
) -> int:
    if not text or source_message is None:
        return 0
    if getattr(source_message, "forward_origin", None) is not None:
        return 0

    user = getattr(source_message, "from_user", None)
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        return 0

    chat_id = _message_chat_id(source_message)
    if chat_id is None:
        return 0
    if not repo.is_capability_enabled(chat_id, capability_cls):
        return 0

    return await process_curse_text(
        repo,
        metrics,
        user_id=user_id,
        text=text,
        source_message=source_message,
        metric_labels={
            "user_id": str(user_id),
            "user_name": _metric_user_name(user, user_id),
        },
    )
