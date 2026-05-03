"""
Lint-style check: features must not reach into the raw python-telegram-bot API.

Each feature under `steward/features/` should go through the framework:
    - Keyboard / Button instead of InlineKeyboardMarkup / InlineKeyboardButton
    - @on_callback + self.cb(...).button(...) instead of hardcoded callback_data strings
    - ctx.reply / ctx.edit / ctx.send_to / ctx.toast instead of message.reply_text,
      chat.send_message, callback_query.message.edit_*
    - @wizard + step() instead of importing Step / SessionHandlerBase directly

This test fails on NEW violations while tolerating a baseline of files that
predate the migration. When you migrate a file, remove its entry from BASELINE.
If you add a new violation to a baselined file (a rule it doesn't already have),
the test fails too.
"""

from __future__ import annotations

import re
from pathlib import Path

FEATURES_DIR = Path(__file__).resolve().parent.parent / "steward" / "features"


RULES: dict[str, tuple[re.Pattern[str], str]] = {
    "raw_inline_keyboard": (
        re.compile(r"\bInlineKeyboard(Markup|Button)\b"),
        "use steward.framework.Keyboard / Button instead of InlineKeyboardMarkup/Button",
    ),
    "raw_telegram_send": (
        re.compile(
            r"\.(reply_text|send_message|send_voice|send_video|send_photo|send_document|send_audio"
            r"|edit_message_text|edit_message_reply_markup|edit_message_caption)\("
        ),
        "use FeatureContext.reply / edit / send_to / delete_or_clear_keyboard instead of raw telegram methods",
    ),
    "raw_session_import": (
        re.compile(
            r"^\s*from\s+steward\.session\.(step|session_handler_base)\s+import",
            re.MULTILINE,
        ),
        "use @wizard + step() from steward.framework instead of importing Step / SessionHandlerBase",
    ),
    "raw_callback_data_pipe": (
        re.compile(r"""callback_data\s*=\s*f?['"][^'"]*\|"""),
        "declare the schema in @on_callback and build buttons via self.cb(...).button(...) "
        "instead of hardcoding callback_data strings with '|'",
    ),
}


# Files that predate the framework migration. Each entry lists the rules a file
# is *allowed* to violate. When migrating a file, remove its entry entirely.
# When you cannot fully migrate in one PR, shrink the set to the minimum.
BASELINE: dict[str, set[str]] = {
    # Step-based wizards (pre-@wizard). Migrating to custom_step() is follow-up work.
    "subscribe/add_session.py": {
        "raw_inline_keyboard",
        "raw_telegram_send",
        "raw_session_import",
        "raw_callback_data_pipe",
    },
    "subscribe/__init__.py": {"raw_telegram_send"},
    "pasha.py": {
        "raw_telegram_send",
        "raw_session_import",
    },
    "rule.py": {
        "raw_inline_keyboard",
        "raw_telegram_send",
        "raw_session_import",
        "raw_callback_data_pipe",
    },
    "broadcast.py": {"raw_telegram_send", "raw_session_import"},

    # Download callbacks — old callback_data schemes, not yet on @on_callback.
    "download/yt.py": {"raw_inline_keyboard", "raw_callback_data_pipe"},
    "download/callbacks.py": {"raw_inline_keyboard"},

    # Media-heavy features that still call send_voice/reply_text for media output.
    # These should move to ctx.reply()/ctx.reply_media() once the helpers exist.
    "voice_video/__init__.py": {"raw_telegram_send"},
    "voice_video/conversion.py": {"raw_telegram_send"},
    "voice_video/transcription.py": {"raw_telegram_send"},
    "multiply.py": {"raw_telegram_send"},
    "newtext.py": {"raw_telegram_send"},
    "tarot.py": {"raw_telegram_send"},
    "watch.py": {"raw_telegram_send"},
    "miniapp.py": {"raw_telegram_send"},
    "react.py": {"raw_telegram_send"},
    "rule_answer.py": {"raw_telegram_send"},
    "message_info.py": {"raw_telegram_send"},
    "id.py": {"raw_telegram_send"},
    "reward.py": {"raw_telegram_send"},
    "todo.py": {"raw_telegram_send"},
    "db.py": {"raw_telegram_send"},
}


def _iter_feature_files():
    for path in FEATURES_DIR.rglob("*.py"):
        if path.name == "__pycache__":
            continue
        yield path


def _file_violations(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    hits: set[str] = set()
    for rule, (pattern, _msg) in RULES.items():
        if pattern.search(text):
            hits.add(rule)
    return hits


def _rel_key(path: Path) -> str:
    return path.relative_to(FEATURES_DIR).as_posix()


def test_features_do_not_use_raw_telegram_api():
    new_violations: list[str] = []
    stale_baseline: list[str] = []

    for path in _iter_feature_files():
        key = _rel_key(path)
        violated = _file_violations(path)
        allowed = BASELINE.get(key, set())

        for rule in sorted(violated - allowed):
            new_violations.append(
                f"  {key}: {rule} — {RULES[rule][1]}"
            )
        for rule in sorted(allowed - violated):
            stale_baseline.append(f"  {key}: {rule}")

    # BASELINE entries that point at nonexistent files (e.g. file deleted).
    all_keys = {_rel_key(p) for p in _iter_feature_files()}
    for key in sorted(set(BASELINE) - all_keys):
        stale_baseline.append(f"  {key}: file no longer exists")

    messages: list[str] = []
    if new_violations:
        messages.append(
            "New raw-Telegram violations in steward/features/ — route through the framework:\n"
            + "\n".join(new_violations)
        )
    if stale_baseline:
        messages.append(
            "BASELINE in tests/test_no_raw_telegram_in_features.py is stale "
            "(rules no longer violated — remove them):\n"
            + "\n".join(stale_baseline)
        )

    assert not messages, "\n\n".join(messages)
