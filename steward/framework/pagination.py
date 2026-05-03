from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Awaitable, Callable

from steward.framework.keyboard import Button, Keyboard


PaginatorResult = (
    tuple[list[Any], Callable[[list[Any]], str]]
    | tuple[list[Any], Callable[[list[Any]], str], Keyboard | None]
)


@dataclass
class _PaginatorSpec:
    name: str
    func: Callable[..., Awaitable[PaginatorResult]]
    per_page: int = 10
    header: str = ""
    empty_text: str = "Список пуст"
    parse_mode: str | None = "markdown"


def paginated(
    name: str,
    *,
    per_page: int = 10,
    header: str = "",
    empty_text: str = "Список пуст",
    parse_mode: str | None = "markdown",
):
    def decorator(func):
        spec = _PaginatorSpec(
            name=name,
            func=func,
            per_page=per_page,
            header=header,
            empty_text=empty_text,
            parse_mode=parse_mode,
        )
        setattr(func, "_feature_paginator", spec)
        return func

    return decorator


def _split_pagination_data(prefix: str, data: str) -> tuple[str, str, int] | None:
    if not data.startswith(prefix + "|"):
        return None
    rest = data[len(prefix) + 1 :]
    parts = rest.split("|")
    if len(parts) < 2:
        return None
    try:
        page = int(parts[-1])
    except ValueError:
        return None
    name = parts[0]
    metadata = "|".join(parts[1:-1])
    return name, metadata, page


def _build_page_keyboard(
    prefix: str,
    name: str,
    metadata: str,
    page: int,
    pages: int,
    extra: Keyboard | None,
) -> Keyboard:
    rows: list[list[Button]] = []
    if pages > 1:
        max_page = pages - 1
        nav: list[Button] = []
        if page > 0:
            nav.append(Button("«", callback_data=f"{prefix}|{name}|{metadata}|0"))
            nav.append(
                Button("‹", callback_data=f"{prefix}|{name}|{metadata}|{page - 1}")
            )
        nav.append(Button(f"{page + 1}/{pages}", callback_data=f"{prefix}|{name}|{metadata}|{page}"))
        if page < max_page:
            nav.append(
                Button("›", callback_data=f"{prefix}|{name}|{metadata}|{page + 1}")
            )
            nav.append(Button("»", callback_data=f"{prefix}|{name}|{metadata}|{max_page}"))
        rows.append(nav)
    kb = Keyboard(rows)
    if extra is not None:
        kb.extend(extra)
    return kb


async def call_paginator(
    spec: _PaginatorSpec,
    feature: Any,
    ctx: Any,
    metadata: str,
) -> tuple[list[Any], Callable[[list[Any]], str], Keyboard | None]:
    result = spec.func(feature, ctx, metadata)
    if isawaitable(result):
        result = await result
    if isinstance(result, tuple):
        if len(result) == 2:
            items, render = result
            extra = None
        elif len(result) == 3:
            items, render, extra = result
        else:
            raise TypeError(f"Paginator {spec.name!r} returned tuple of len {len(result)}")
    else:
        raise TypeError(f"Paginator {spec.name!r} must return (items, render[, extra_keyboard])")
    return items, render, extra
