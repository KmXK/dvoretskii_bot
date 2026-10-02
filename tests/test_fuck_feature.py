from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import steward.features.fuck as fuck
from steward.data.models.fuck_asset import FuckAsset
from tests.conftest import make_repository


def make_context(user_id=123, chat_id=-100123, message_id=77, **message_fields):
    values = {
        "message_id": message_id,
        "from_user": SimpleNamespace(
            id=user_id,
            username="alice",
            first_name="Alice",
        ),
        "photo": None,
        "animation": None,
        "document": None,
        "reply_to_message": None,
        "entities": (),
    }
    values.update(message_fields)
    message = SimpleNamespace(**values)
    return SimpleNamespace(
        chat_id=chat_id,
        user_id=user_id,
        message=message,
        reply=AsyncMock(),
    )


def make_asset():
    return FuckAsset(
        id="asset-42",
        owner_id=9,
        name="office fight",
        scope="global",
        extension="gif",
        created_at=1,
    )


@pytest.fixture
def compose(monkeypatch, tmp_path):
    asset = make_asset()
    source = tmp_path / "asset.gif"
    annotation = {"keyframes": {}}
    monkeypatch.setattr(
        fuck,
        "_pick_random_asset",
        Mock(return_value=(asset, source, annotation)),
    )
    monkeypatch.setattr(fuck, "check_limit", lambda *_args: None)
    render = AsyncMock()
    monkeypatch.setattr(fuck, "render_and_send", render)
    return render, asset, source, annotation


def media(file_id="media-id", **fields):
    return SimpleNamespace(file_id=file_id, **fields)


async def test_reply_animation_is_used_before_sender_avatar(compose):
    render, _, _, _ = compose
    reply_animation = media(
        "reply-animation",
        width=320,
        height=240,
        duration=2,
        file_size=100,
    )
    ctx = make_context(
        reply_to_message=SimpleNamespace(
            from_user=SimpleNamespace(id=456, username="target", first_name="Target"),
            photo=None,
            animation=reply_animation,
            document=None,
        )
    )
    feature = fuck.FuckFeature()
    feature.repository = make_repository()

    await feature.do_reply(ctx)

    assert render.await_args.kwargs["b_media"] is reply_animation
    assert render.await_args.args[3:7] == (123, "Alice", 0, None)


async def test_reply_photo_is_used_as_target_media(compose):
    render, _, _, _ = compose
    reply_photo = media("reply-photo", width=640, height=480, file_size=200)
    ctx = make_context(
        reply_to_message=SimpleNamespace(
            from_user=SimpleNamespace(id=456, username="target", first_name="Target"),
            photo=[reply_photo],
            animation=None,
            document=None,
        )
    )
    feature = fuck.FuckFeature()
    feature.repository = make_repository()

    await feature.do_reply(ctx)

    assert render.await_args.kwargs["b_media"] is reply_photo


async def test_command_media_has_priority_over_reply_media(compose):
    render, _, _, _ = compose
    command_animation = media("command-animation", width=320, height=240, duration=1)
    reply_animation = media("reply-animation", width=640, height=480, duration=2)
    ctx = make_context(
        animation=command_animation,
        reply_to_message=SimpleNamespace(
            from_user=SimpleNamespace(id=456, username="target", first_name="Target"),
            photo=None,
            animation=reply_animation,
            document=None,
        ),
    )
    feature = fuck.FuckFeature()
    feature.repository = make_repository()

    await feature.do_reply(ctx)

    assert render.await_args.kwargs["b_media"] is command_animation


async def test_document_gif_is_used_as_target_media(compose):
    render, _, _, _ = compose
    document = media(
        "document-gif",
        mime_type="application/octet-stream",
        file_name="dance.GIF",
        file_size=500,
    )
    ctx = make_context(document=document)
    feature = fuck.FuckFeature()
    feature.repository = make_repository()

    await feature.do_reply(ctx)

    assert render.await_args.kwargs["b_media"] is document


async def test_malformed_document_falls_back_to_reply_sender(compose):
    render, _, _, _ = compose
    ctx = make_context(
        document=media(
            "pdf-id",
            mime_type="application/pdf",
            file_name="document.mp4",
        ),
        reply_to_message=SimpleNamespace(
            from_user=SimpleNamespace(id=456, username="target", first_name="Target"),
            photo=None,
            animation=None,
            document=None,
        ),
    )
    feature = fuck.FuckFeature()
    feature.repository = make_repository()

    await feature.do_reply(ctx)

    assert render.await_args.kwargs["b_media"] is None
    assert render.await_args.args[5:7] == (456, "Target")


async def test_supported_media_limit_error_is_replied(compose):
    render, _, _, _ = compose
    render.side_effect = ValueError("Файл слишком большой")
    animation = media("large-animation", width=10000, height=10000, duration=60)
    ctx = make_context(animation=animation)
    feature = fuck.FuckFeature()
    feature.repository = make_repository()

    await feature.do_reply(ctx)

    ctx.reply.assert_awaited_once_with("Файл слишком большой")
    assert render.await_args.kwargs["b_media"] is animation


async def test_explicit_user_keeps_avatar_target_even_with_media(compose):
    render, _, _, _ = compose
    command_animation = media("command-animation", width=320, height=240, duration=1)
    ctx = make_context(animation=command_animation)
    feature = fuck.FuckFeature()
    feature.repository = make_repository()

    await feature.do(ctx, "456")

    assert render.await_args.args[5:7] == (456, None)
    assert render.await_args.kwargs["b_media"] is None


async def test_sex_photo_reply_keeps_two_media_compatibility(compose):
    render, _, _, _ = compose
    author_photo = media("author-photo", width=640, height=480, file_size=100)
    target_photo = media("target-photo", width=640, height=480, file_size=100)
    ctx = make_context(
        photo=[author_photo],
        reply_to_message=SimpleNamespace(
            photo=[target_photo],
            animation=None,
            document=None,
        ),
    )
    feature = fuck.SexFeature()
    feature.repository = make_repository()

    assert await feature._try_photos(ctx)

    assert render.await_args.kwargs["a_media"] is author_photo
    assert render.await_args.kwargs["b_media"] is target_photo


async def test_rate_limit_happens_before_asset_selection(compose, monkeypatch):
    render, _, _, _ = compose
    selected = Mock(side_effect=AssertionError("asset selection must wait"))
    rate_limit_error = fuck.BucketFullException.__new__(fuck.BucketFullException)
    monkeypatch.setattr(fuck, "_pick_random_asset", selected)
    monkeypatch.setattr(
        fuck,
        "check_limit",
        Mock(side_effect=rate_limit_error),
    )
    ctx = make_context(animation=media("animation"))
    feature = fuck.FuckFeature()
    feature.repository = make_repository()

    await feature.do_reply(ctx)

    selected.assert_not_called()
    render.assert_not_awaited()
    ctx.reply.assert_awaited_once_with("Слишком часто. Не больше 2 в минуту, остынь.")
