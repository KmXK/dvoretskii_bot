import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

import steward.features.fuck as fuck
from steward.data.models.fuck_asset import FuckAsset
from tests.conftest import make_repository


@pytest.fixture
def compose_lock(monkeypatch):
    lock = asyncio.Lock()
    monkeypatch.setattr(fuck, "_COMPOSE_LOCK", lock)
    monkeypatch.setattr(
        fuck,
        "available_memory_bytes",
        lambda: fuck.MIN_AVAILABLE_MEMORY_BYTES,
    )
    monkeypatch.setattr(fuck, "check_limit", lambda *_args: None)
    return lock


def make_context(user_id=123, chat_id=-100123, message_id=77):
    return SimpleNamespace(
        chat_id=chat_id,
        user_id=user_id,
        message=SimpleNamespace(
            message_id=message_id,
            from_user=SimpleNamespace(
                id=user_id,
                username="alice",
                first_name="Alice",
            ),
            photo=None,
        ),
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


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (RuntimeError("worker failed"), "render failed"),
        (TimeoutError(), "render timed out"),
    ],
)
async def test_render_logs_asset_context_for_failure_and_timeout(
    monkeypatch,
    caplog,
    compose_lock,
    tmp_path,
    error,
    outcome,
):
    repo = make_repository()
    feature = fuck.FuckFeature()
    feature.repository = repo
    feature.bot = SimpleNamespace(send_animation=AsyncMock())
    ctx = make_context()
    asset = make_asset()
    source = tmp_path / "asset.gif"
    monkeypatch.setattr(
        fuck,
        "_pick_random_asset",
        Mock(return_value=(asset, source, {"keyframes": {}})),
    )
    monkeypatch.setattr(
        feature,
        "_load_avatar",
        AsyncMock(return_value=Image.new("RGBA", (8, 8), "white")),
    )

    async def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(fuck, "run_render_job", fail)
    caplog.set_level(logging.INFO, logger=fuck.logger.name)

    await feature._compose_and_send(
        ctx,
        1,
        "Alice",
        2,
        "Bob",
        tag="/fuck",
    )

    messages = [record.getMessage() for record in caplog.records]
    started_index = next(
        index
        for index, message in enumerate(messages)
        if "render started" in message
    )
    outcome_index = next(
        index
        for index, message in enumerate(messages)
        if outcome in message
    )
    context_values = (
        f"asset_id={asset.id}",
        f"asset_name={asset.name!r}",
        f"chat_id={ctx.chat_id}",
        f"user_id={ctx.user_id}",
        f"message_id={ctx.message.message_id}",
    )
    assert started_index < outcome_index
    assert all(
        value in messages[started_index]
        and value in messages[outcome_index]
        for value in context_values
    )


@pytest.mark.parametrize(
    ("feature_cls", "tag"),
    [(fuck.FuckFeature, "/fuck"), (fuck.SexFeature, "/sex")],
)
async def test_busy_rejects_before_selecting_or_loading(
    monkeypatch,
    compose_lock,
    feature_cls,
    tag,
):
    repo = make_repository()
    feature = feature_cls()
    feature.repository = repo
    ctx = make_context()
    selected = Mock(side_effect=AssertionError("asset selection must be deferred"))
    memory = Mock(side_effect=AssertionError("memory check must be deferred"))
    load_avatar = AsyncMock(side_effect=AssertionError("avatar loading must be deferred"))
    render = AsyncMock(side_effect=AssertionError("render must be deferred"))
    monkeypatch.setattr(fuck, "_pick_random_asset", selected)
    monkeypatch.setattr(fuck, "available_memory_bytes", memory)
    monkeypatch.setattr(feature, "_load_avatar", load_avatar)
    monkeypatch.setattr(fuck, "run_render_job", render)
    await compose_lock.acquire()
    try:
        await feature._compose_and_send(
            ctx,
            1,
            "Alice",
            2,
            "Bob",
            tag=tag,
        )
    finally:
        compose_lock.release()

    ctx.reply.assert_awaited_once_with("Генератор занят, попробуй чуть позже")
    selected.assert_not_called()
    memory.assert_not_called()
    load_avatar.assert_not_awaited()
    render.assert_not_awaited()


async def test_low_memory_rejects_before_asset_or_avatar_work(
    monkeypatch,
    compose_lock,
):
    repo = make_repository()
    feature = fuck.FuckFeature()
    feature.repository = repo
    ctx = make_context()
    selected = Mock()
    load_avatar = AsyncMock()
    render = AsyncMock()
    monkeypatch.setattr(
        fuck,
        "available_memory_bytes",
        lambda: fuck.MIN_AVAILABLE_MEMORY_BYTES - 1,
    )
    monkeypatch.setattr(fuck, "_pick_random_asset", selected)
    monkeypatch.setattr(feature, "_load_avatar", load_avatar)
    monkeypatch.setattr(fuck, "run_render_job", render)

    await feature._compose_and_send(
        ctx,
        1,
        "Alice",
        2,
        "Bob",
        tag="/fuck",
    )

    ctx.reply.assert_awaited_once_with(
        "Сейчас не хватает ресурсов для генерации, попробуй позже"
    )
    selected.assert_not_called()
    load_avatar.assert_not_awaited()
    render.assert_not_awaited()
    assert not compose_lock.locked()


async def test_photo_command_defers_download_until_slot_and_passes_b_id(
    monkeypatch,
    compose_lock,
):
    repo = make_repository()
    feature = fuck.FuckFeature()
    feature.repository = repo
    message = SimpleNamespace(
        message_id=77,
        from_user=SimpleNamespace(id=123, username="alice", first_name="Alice"),
        photo=[SimpleNamespace(file_id="photo-id")],
    )
    ctx = make_context()
    ctx.message = message
    photo_loader = AsyncMock(side_effect=AssertionError("photo must wait for the lock"))
    monkeypatch.setattr(feature, "_photo_from_attachment", photo_loader)

    await compose_lock.acquire()
    try:
        await feature.do_reply(ctx)
    finally:
        compose_lock.release()

    photo_loader.assert_not_awaited()
    ctx.reply.assert_awaited_once_with("Генератор занят, попробуй чуть позже")

    compose = AsyncMock()
    monkeypatch.setattr(feature, "_compose_and_send", compose)
    await feature._run_with_target_photo(ctx, message)
    kwargs = compose.await_args.kwargs
    assert kwargs["b_id"] == 0
    assert kwargs["b_photo"] is message
