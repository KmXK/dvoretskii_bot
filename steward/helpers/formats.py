import html as _html


def spoiler_block(text: str, header: str = "") -> str:
    """HTML expandable blockquote — a "spoiler" that stays partially visible
    and unfolds on tap. Body and header are HTML-escaped; send with
    parse_mode="HTML".
    """
    body = _html.escape(text)
    if header:
        header_html = f"<b>{_html.escape(header)}</b>\n"
    else:
        header_html = ""
    return f"<blockquote expandable>{header_html}{body}</blockquote>"


def spoiler_inline(text: str) -> str:
    """HTML inline spoiler — text is hidden until the user taps it. The whole
    thing is HTML-escaped; send with parse_mode="HTML".
    """
    return f"<tg-spoiler>{_html.escape(text)}</tg-spoiler>"


def escape_markdown(text: str) -> str:
    return (
        text.replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def format_lined_list[T](items: list[tuple[T, str]], delimiter: str = ". "):
    max_number_item = max(items, key=lambda x: len(str(x[0])))
    max_length = len(str(max_number_item[0]))
    return "\n".join([
        (f"`{str(item[0]).rjust(max_length)}`" + delimiter + item[1]) for item in items
    ])


def union_lists[T](lists: list[list[T] | T]) -> list[T]:
    result = []
    for x in lists:
        if isinstance(x, list):
            result.extend(x)
        else:
            result.append(x)
    print(result)
    return result
