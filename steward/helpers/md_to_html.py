"""Convert a useful subset of Markdown to Telegram-flavored HTML.

Telegram's legacy `Markdown` parse_mode is fragile: any unescaped `_`, `*`, `[`
or backtick in the model's output blows up the whole message. HTML mode is
much more permissive — we only have to escape `<`, `>`, `&` and emit a small
set of tags.

This converter handles the patterns LLMs actually produce:
- ```fenced``` code blocks (with optional language tag)
- `inline` code
- **bold** / __bold__
- *italic* / _italic_
- [text](url) links
- ~~strikethrough~~
"""
from __future__ import annotations

import html
import re

_FENCED_CODE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_STAR_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_BOLD_UNDER_RE = re.compile(r"(?<![a-zA-Z0-9_])__([^_\n]+?)__(?![a-zA-Z0-9_])")
_ITALIC_STAR_RE = re.compile(r"(?<![a-zA-Z0-9*])\*([^*\n]+?)\*(?![a-zA-Z0-9])")
_ITALIC_UNDER_RE = re.compile(r"(?<![a-zA-Z0-9_])_([^_\n]+?)_(?![a-zA-Z0-9_])")
_STRIKE_RE = re.compile(r"~~([^~\n]+?)~~")
_LINK_RE = re.compile(r"\[([^\]\n]+?)\]\(([^)\s]+?)\)")


def md_to_html(text: str) -> str:
    """Convert Markdown text to Telegram HTML. Safe to call on plain text."""
    if not text:
        return text

    placeholders: list[str] = []

    def _stash(content: str) -> str:
        placeholders.append(content)
        return f"\x00{len(placeholders) - 1}\x00"

    def _stash_fenced(match: re.Match[str]) -> str:
        return _stash(f"<pre>{html.escape(match.group(2))}</pre>")

    def _stash_inline(match: re.Match[str]) -> str:
        return _stash(f"<code>{html.escape(match.group(1))}</code>")

    text = _FENCED_CODE_RE.sub(_stash_fenced, text)
    text = _INLINE_CODE_RE.sub(_stash_inline, text)

    text = html.escape(text, quote=False)

    text = _BOLD_STAR_RE.sub(r"<b>\1</b>", text)
    text = _BOLD_UNDER_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_STAR_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_UNDER_RE.sub(r"<i>\1</i>", text)
    text = _STRIKE_RE.sub(r"<s>\1</s>", text)
    text = _LINK_RE.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', text)

    def _restore(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return placeholders[idx]

    text = re.sub(r"\x00(\d+)\x00", _restore, text)
    return text
