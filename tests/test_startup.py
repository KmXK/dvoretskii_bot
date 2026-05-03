"""Smoke tests for bot startup.

These don't run a real polling loop or open the API port; they instantiate
the parts that run during `main()` and check they don't raise, so an
accidental rename / missing import / invalid decorator is caught quickly.
"""

from __future__ import annotations

import pytest

from steward.bot.inline_hints_updater import _command_entry
from steward.features._special.ai_router import AiRouterHandler
from steward.features._special.help import HelpFeature
from steward.features.registry import all_features
from steward.handlers.handler import Handler
from tests.conftest import make_repository


_TG_COMMAND_NAME_LIMIT = 32
_TG_COMMAND_DESCRIPTION_LIMIT = 256


def _assemble_handlers() -> list[Handler]:
    """Mirror main.get_handlers() without LogsFeature (which needs a path)."""
    handlers: list[Handler] = all_features()
    handlers.append(AiRouterHandler(handlers))
    handlers.append(HelpFeature(handlers))
    return handlers


def test_all_features_construct():
    handlers = _assemble_handlers()
    assert len(handlers) > 10, "suspiciously few features — did registry load?"
    for h in handlers:
        assert isinstance(h, Handler)


def test_no_duplicate_commands():
    handlers = _assemble_handlers()
    seen: dict[str, str] = {}
    for h in handlers:
        for name in getattr(h, "get_command_with_aliases", lambda: [])():
            owner = type(h).__name__
            if name in seen and seen[name] != owner:
                pytest.fail(
                    f"Command /{name} is registered by both "
                    f"{seen[name]} and {owner}"
                )
            seen[name] = owner


def test_inline_hints_within_telegram_limits():
    """Every command the bot asks Telegram to register must fit the Bot API.

    - Command name: 1-32 chars, [a-z0-9_], with an optional leading `/`.
    - Description: 1-256 chars, non-empty.
    This mirrors the payload we build in InlineHintsUpdater._set_commands.
    """
    handlers = _assemble_handlers()
    entries = [e for e in (_command_entry(h) for h in handlers) if e is not None]
    assert entries, "no commands would be sent to set_my_commands"

    seen_names: set[str] = set()
    for name, description in entries:
        assert 1 <= len(description) <= _TG_COMMAND_DESCRIPTION_LIMIT, (
            f"{name}: description length {len(description)} out of range"
        )
        core = name.lstrip("/")
        assert 1 <= len(core) <= _TG_COMMAND_NAME_LIMIT, (
            f"{name}: command name length {len(core)} out of range"
        )
        assert core not in seen_names, f"duplicate command name: {core}"
        seen_names.add(core)


async def test_feature_init_hooks_do_not_raise(monkeypatch):
    """Every Feature's @on_init must succeed against a blank repository.

    AIFeature's on_init calls the real OpenRouter (to warm the thinking-phrase
    cache), so we stub that one call out — startup itself should never depend
    on network being reachable.
    """
    import steward.features.ai as ai_module
    import steward.helpers.thinking as thinking

    async def _fake_warm_cache(ai_call):
        return None

    monkeypatch.setattr(thinking, "ensure_cached", _fake_warm_cache)
    monkeypatch.setattr(ai_module, "ensure_thinking_phrases", _fake_warm_cache)

    handlers = _assemble_handlers()
    repo = make_repository()
    for h in handlers:
        h.repository = repo
        h.bot = None  # type: ignore[assignment]
        await h.init()


def test_main_module_imports():
    """`main.py` must load (mirrors `python main.py` at import time).

    Skips when the optional `chess` dep (used by boardgames websocket code)
    is unavailable in the local venv. CI / docker image install it.
    """
    pytest.importorskip("chess")
    import importlib
    import main  # noqa: F401
    importlib.reload(main)
