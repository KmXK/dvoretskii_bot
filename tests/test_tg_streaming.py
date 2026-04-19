"""Unit tests for stream_reply — mocks the Message object to observe the
sequence of edit_text calls."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from steward.helpers import thinking
from steward.helpers.tg_streaming import stream_reply


def _fake_target():
    sent = MagicMock()
    sent.edit_text = AsyncMock()

    target = MagicMock()
    target.reply_text = AsyncMock(return_value=sent)
    return target, sent


async def _stream_from(items: list[str], delay: float = 0.0):
    for x in items:
        if delay:
            await asyncio.sleep(delay)
        yield x


async def test_stream_reply_sends_random_placeholder_then_streams():
    thinking.reset_for_tests()
    target, sent = _fake_target()

    await stream_reply(target, _stream_from(["hello ", "world"]))

    # The first thing the user sees is a random "думаю…" phrase in italic HTML.
    placeholder_call = target.reply_text.await_args
    assert placeholder_call.kwargs.get("parse_mode") == "HTML"
    assert placeholder_call.args[0].startswith("<i>")
    # Final edit applies the full streamed text.
    final_edit = sent.edit_text.await_args_list[-1]
    assert final_edit.args[0] == "hello world"


async def test_stream_reply_hot_swaps_placeholder_on_upgrade():
    thinking.reset_for_tests()
    target, sent = _fake_target()

    upgrade_done = asyncio.Event()

    async def slow_upgrade() -> str | None:
        await asyncio.sleep(0.05)
        upgrade_done.set()
        return "Ищу карточку в поликлинике…"

    async def chunks():
        # Wait for upgrade to happen before streaming starts so the upgrade
        # edit is observable before the token edits take over.
        await upgrade_done.wait()
        yield "ответ"

    await stream_reply(
        target,
        chunks(),
        placeholder_upgrade=slow_upgrade(),
    )

    edits = [c.args[0] for c in sent.edit_text.await_args_list]
    upgrade_edits = [e for e in edits if "карточку" in e.lower()]
    assert upgrade_edits, f"upgraded placeholder never rendered; edits={edits}"
    # After upgrade, the italic HTML base should use the new phrase.
    assert any(
        e.startswith("<i>") and "Ищу карточку в поликлинике" in e
        for e in upgrade_edits
    )
    # Final plain edit is the streamed content.
    assert edits[-1] == "ответ"


async def test_stream_reply_keeps_placeholder_when_upgrade_resolves_none():
    thinking.reset_for_tests()
    target, sent = _fake_target()

    async def no_upgrade() -> str | None:
        return None

    await stream_reply(
        target,
        _stream_from(["ok"]),
        placeholder_upgrade=no_upgrade(),
    )

    edits = [c.args[0] for c in sent.edit_text.await_args_list]
    # No HTML edit except possibly the ongoing animation (which wouldn't fire
    # in this race-free scenario). Final must be "ok".
    assert edits[-1] == "ok"


async def test_stream_reply_ignores_upgrade_failure():
    thinking.reset_for_tests()
    target, sent = _fake_target()

    async def broken_upgrade() -> str | None:
        raise RuntimeError("gemini is down")

    await stream_reply(
        target,
        _stream_from(["still works"]),
        placeholder_upgrade=broken_upgrade(),
    )

    edits = [c.args[0] for c in sent.edit_text.await_args_list]
    assert edits[-1] == "still works"
