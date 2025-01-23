import logging
from dataclasses import dataclass
from math import ceil
from typing import Any, Callable, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

logger = logging.getLogger("pagination")


def is_int_string(s: str):
    if s[0] in ("-", "+"):
        return s[1:].isdigit()
    return s.isdigit()


@dataclass
class PaginationParseResult:
    unique_keyboard_name: str
    page_number: int
    metadata: str
    is_current_page: bool


class ParsePaginationException(Exception):
    def __init__(self, msg):
        super(msg)


def parse(
    callback_data: str,
    delimiter: str = "|",
    current_page_marker: str = "~",
) -> PaginationParseResult:
    parts = callback_data.split(delimiter)

    if len(parts) != 3:
        raise ParsePaginationException("Invalid parts count")

    if len(parts[2]) == 0:
        raise ParsePaginationException("Empty page number")

    is_current_page = False
    if parts[2][0] == current_page_marker:
        is_current_page = True
        parts[2] = parts[2][1::]

    if not is_int_string(parts[2]):
        raise ParsePaginationException("Page number must be integer")

    return PaginationParseResult(
        unique_keyboard_name=parts[0],
        metadata=parts[1],
        page_number=int(parts[2]),
        is_current_page=is_current_page,
    )


def parse_and_validate(
    unique_keyboard_name: str,
    callback_data: str,
    **kwargs,
) -> Optional[PaginationParseResult]:
    try:
        result = parse(callback_data, **kwargs)
        if result.unique_keyboard_name == unique_keyboard_name:
            return result
        return None
    except ParsePaginationException as e:
        logger.exception(e)
        return None


def create_pagination_keyboard(
    unique_keyboard_name: str,
    current_page: int,
    pages_count: int,
    allow_edges: bool = True,
    show_edges_for_first_and_last_pages: bool = True,
    metadata: str | Callable[[int], str] = "",
    delimiter: str = "|",
    current_page_marker: str = "~",
):
    max_page_number = pages_count - 1

    buttons = [
        ["<", current_page - 1 if current_page > 0 else 0],
        [f"{current_page + 1}/{pages_count}", current_page],
        [">", current_page + 1 if current_page < max_page_number else max_page_number],
    ]

    if allow_edges:
        if show_edges_for_first_and_last_pages or current_page > 0:
            buttons.insert(0, ["<<<", 0])
        if show_edges_for_first_and_last_pages or current_page < max_page_number:
            buttons.append([">>>", max_page_number])

    keyboard = [
        InlineKeyboardButton(
            button[0],
            callback_data=(
                delimiter.join(
                    [
                        unique_keyboard_name,
                        metadata if isinstance(metadata, str) else metadata(button[1]),
                        (
                            f"{current_page_marker}{button[1]}"
                            if button[1] == current_page
                            else str(button[1])
                        ),
                    ]
                )
            ),
        )
        for button in buttons
    ]

    return InlineKeyboardMarkup([keyboard])


@dataclass
class FormatItemContext:
    item_number: int
    total_items: int
    page_first_item_number: int
    page_last_item_number: int


def page_wrapper_format(
    pre_text: str = "",
    post_text: str = "",
):
    def wrapper(item, context: FormatItemContext):
        if context.item_number == context.page_first_item_number:
            item = pre_text + str(item)
        if context.item_number == context.page_last_item_number:
            item = str(item) + post_text
        return item

    return wrapper


def get_pages_count(items_count: int, page_size: int):
    return ceil(items_count / page_size)


def get_data_page(
    data: list[Any],
    page: int | None,
    page_size: int,
    list_header: str | None,
    unique_keyboard_name: str,
    item_format_func: Callable[[Any, FormatItemContext], str] = lambda x, _: str(x),
    always_show_pagination: bool = False,
    delimiter: str = "\n",
    start_from_last_page: bool = False,
):
    length = len(data)
    if length <= page_size or page is None:
        page = get_pages_count(length, page_size) - 1 if start_from_last_page else 0

    start_index = page * page_size
    last_index = min(length - 1, start_index + page_size - 1)

    return (
        ("" if list_header is None else f"{str(list_header)}\n\n")
        + delimiter.join(
            [
                item_format_func(
                    fq,
                    FormatItemContext(
                        item_number=i + start_index,
                        total_items=length,
                        page_first_item_number=start_index,
                        page_last_item_number=last_index,
                    ),
                )
                for i, fq in enumerate(data[start_index : last_index + 1])
            ]
        ),
        create_pagination_keyboard(
            unique_keyboard_name,
            current_page=page,
            pages_count=get_pages_count(length, page_size),
        )
        if length > page_size or always_show_pagination
        else None,
    )


class Paginator:
    def __init__(
        self,
        unique_keyboard_name: str,
        list_header: str | None,
        page_size: int,
        data_func: Callable[[], list[Any]],
        item_format_func: Callable[[Any, FormatItemContext], str] = lambda x, _: str(x),
        always_show_pagination: bool = True,
        delimiter: str = "\n",
        start_from_last_page: bool = False,
    ):
        self.unique_keyboard_name = unique_keyboard_name
        self.list_header = list_header
        self.page_size = page_size
        self.data_func = data_func
        self.item_format_func = item_format_func
        self.always_show_pagination = always_show_pagination
        self.delimiter = delimiter
        self.start_from_last_page = start_from_last_page

    async def show_list(self, update: Update):
        text, keyboard = self._get_data_page()
        await update.message.reply_text(
            text=text,
            parse_mode="markdown",
            reply_markup=keyboard,
        )
        return True

    async def process_callback(self, update: Update):
        parsed = parse_and_validate(
            self.unique_keyboard_name,
            update.callback_query.data,
        )

        if parsed is None:
            return False

        if not parsed.is_current_page:
            text, keyboard = self._get_data_page(parsed.page_number)
            await update.callback_query.message.edit_text(
                text=text,
                reply_markup=keyboard,
                parse_mode="markdown",
            )

        return True

    def _get_data_page(self, page: int | None = None):
        return get_data_page(
            data=self.data_func(),
            page=page,
            page_size=self.page_size,
            list_header=self.list_header,
            unique_keyboard_name=self.unique_keyboard_name,
            item_format_func=self.item_format_func,
            always_show_pagination=self.always_show_pagination,
            delimiter=self.delimiter,
            start_from_last_page=self.start_from_last_page,
        )
