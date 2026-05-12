"""Tests for the Markdown → Telegram-HTML converter."""
from steward.helpers.md_to_html import md_to_html


def test_plain_text_unchanged():
    assert md_to_html("hello world") == "hello world"


def test_empty():
    assert md_to_html("") == ""


def test_html_chars_escaped():
    assert md_to_html("1 < 2 & 3 > 0") == "1 &lt; 2 &amp; 3 &gt; 0"


def test_bold_stars():
    assert md_to_html("**bold**") == "<b>bold</b>"


def test_italic_stars():
    assert md_to_html("*italic*") == "<i>italic</i>"


def test_italic_underscore():
    assert md_to_html("_italic_") == "<i>italic</i>"


def test_inline_code():
    assert md_to_html("call `foo()`") == "call <code>foo()</code>"


def test_inline_code_escapes_inside():
    assert md_to_html("`a<b>`") == "<code>a&lt;b&gt;</code>"


def test_fenced_code_block():
    out = md_to_html("```python\nprint(1)\n```")
    assert "<pre>" in out
    assert "print(1)" in out


def test_link():
    out = md_to_html("see [Google](https://google.com)")
    assert '<a href="https://google.com">Google</a>' in out


def test_link_with_underscore_url():
    out = md_to_html("see [docs](https://example.com/path_to/thing)")
    assert '<a href="https://example.com/path_to/thing">docs</a>' in out


def test_strike():
    assert md_to_html("~~old~~") == "<s>old</s>"


def test_mixed():
    out = md_to_html("**bold** and [link](https://x.y) and `code`")
    assert "<b>bold</b>" in out
    assert '<a href="https://x.y">link</a>' in out
    assert "<code>code</code>" in out


def test_does_not_italicize_inside_word():
    """foo_bar_baz shouldn't be parsed as italic."""
    assert md_to_html("foo_bar_baz") == "foo_bar_baz"


def test_does_not_italicize_inside_bold():
    """**bold text** should not get extra italic tags from internal *."""
    out = md_to_html("**word**")
    assert out == "<b>word</b>"
