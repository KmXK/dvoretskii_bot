from types import SimpleNamespace

from steward.helpers.message_origin import resolve_message_author


def _user(user_id: int, username: str, first_name: str):
    return SimpleNamespace(
        id=user_id,
        username=username,
        first_name=first_name,
    )


def test_regular_message_uses_sender():
    sender = _user(1, "sender", "Sender")
    author = resolve_message_author(
        SimpleNamespace(from_user=sender, forward_origin=None)
    )

    assert author.user_id == 1
    assert author.username == "sender"
    assert author.first_name == "Sender"
    assert author.can_count_curses


def test_foreign_user_forward_uses_original_author_and_skips_curses():
    forwarder = _user(1, "forwarder", "Forwarder")
    original = _user(2, "original", "Original")
    author = resolve_message_author(
        SimpleNamespace(
            from_user=forwarder,
            forward_origin=SimpleNamespace(sender_user=original),
        )
    )

    assert author.user_id == 2
    assert author.username == "original"
    assert author.first_name == "Original"
    assert not author.can_count_curses


def test_self_forward_uses_original_author_and_counts_curses():
    sender = _user(1, "sender", "Sender")
    author = resolve_message_author(
        SimpleNamespace(
            from_user=sender,
            forward_origin=SimpleNamespace(sender_user=sender),
        )
    )

    assert author.user_id == 1
    assert author.is_self_forward
    assert author.can_count_curses


def test_hidden_forward_uses_hidden_name_and_skips_curses():
    forwarder = _user(1, "forwarder", "Forwarder")
    author = resolve_message_author(
        SimpleNamespace(
            from_user=forwarder,
            forward_origin=SimpleNamespace(sender_user_name="Hidden Person"),
        )
    )

    assert author.user_id is None
    assert author.fallback_name == "Hidden Person"
    assert not author.can_count_curses


def test_channel_forward_uses_channel_title():
    forwarder = _user(1, "forwarder", "Forwarder")
    author = resolve_message_author(
        SimpleNamespace(
            from_user=forwarder,
            forward_origin=SimpleNamespace(
                chat=SimpleNamespace(title="Voice Channel", username="voice_channel"),
                author_signature=None,
            ),
        )
    )

    assert author.user_id is None
    assert author.fallback_name == "Voice Channel"
    assert not author.can_count_curses
