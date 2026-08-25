from dataclasses import dataclass


@dataclass(frozen=True)
class MessageAuthor:
    user_id: int | None
    username: str | None
    first_name: str | None
    fallback_name: str | None
    is_forwarded: bool
    is_self_forward: bool

    @property
    def can_count_curses(self) -> bool:
        return self.user_id is not None and (
            not self.is_forwarded or self.is_self_forward
        )

    @property
    def metric_name(self) -> str:
        return self.username or self.first_name or str(self.user_id)


def _chat_name(chat, signature: str | None) -> str | None:
    if signature:
        return signature
    title = getattr(chat, "title", None)
    if title:
        return title
    username = getattr(chat, "username", None)
    if username:
        return f"@{username}"
    return None


def resolve_message_author(source) -> MessageAuthor:
    forwarder = getattr(source, "from_user", None)
    origin = getattr(source, "forward_origin", None)
    if origin is None and forwarder is None:
        origin = getattr(source, "origin", None)

    if origin is None:
        return MessageAuthor(
            user_id=getattr(forwarder, "id", None),
            username=getattr(forwarder, "username", None),
            first_name=getattr(forwarder, "first_name", None),
            fallback_name=None,
            is_forwarded=False,
            is_self_forward=False,
        )

    sender_user = getattr(origin, "sender_user", None)
    if sender_user is not None:
        sender_id = getattr(sender_user, "id", None)
        return MessageAuthor(
            user_id=sender_id,
            username=getattr(sender_user, "username", None),
            first_name=getattr(sender_user, "first_name", None),
            fallback_name=None,
            is_forwarded=True,
            is_self_forward=(
                sender_id is not None
                and sender_id == getattr(forwarder, "id", None)
            ),
        )

    hidden_name = getattr(origin, "sender_user_name", None)
    if hidden_name:
        return MessageAuthor(
            user_id=None,
            username=None,
            first_name=None,
            fallback_name=hidden_name,
            is_forwarded=True,
            is_self_forward=False,
        )

    chat = getattr(origin, "sender_chat", None) or getattr(origin, "chat", None)
    return MessageAuthor(
        user_id=None,
        username=None,
        first_name=None,
        fallback_name=_chat_name(
            chat,
            getattr(origin, "author_signature", None),
        ),
        is_forwarded=True,
        is_self_forward=False,
    )
