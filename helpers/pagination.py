import logging
from dataclasses import dataclass
from math import ceil
from typing import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from helpers.keyboard import (
    KeyboardParseException,
    KeyboardParseResult,
    parse_and_validate_keyboard,
)

logger = logging.getLogger("pagination")


def is_int_string(s: str):
    if s[0] in ("-", "+"):
        return s[1:].isdigit()
    return s.isdigit()


@dataclass
class PaginationParseResult(KeyboardParseResult):
    page_number: int
    is_current_page: bool


class ParsePaginationException(KeyboardParseException):
    pass


def parse_pagination(
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
        [f"{current_page + 1}/{1 if pages_count == 0 else pages_count}", current_page],
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
                delimiter.join([
                    unique_keyboard_name,
                    metadata if isinstance(metadata, str) else metadata(button[1]),
                    (
                        f"{current_page_marker}{button[1]}"
                        if button[1] == current_page
                        else str(button[1])
                    ),
                ])
            ),
        )
        for button in buttons
    ]

    return keyboard


@dataclass
class PageFormatContext[T]:
    data: list[T]
    page_items_range: tuple[int, int]


def get_pages_count(items_count: int, page_size: int):
    return ceil(items_count / page_size)


def join_page_data_func[T](
    format_func: Callable[[T, PageFormatContext[T]], str] = lambda x, _: str(x),
    delimiter="\n",
):
    def wrapper(ctx: PageFormatContext[T]):
        return delimiter.join([format_func(x, ctx) for x in ctx.data])

    return wrapper


def get_data_page[T](
    data: list[T],
    page: int | None,
    page_size: int,
    list_header: str | None,
    unique_keyboard_name: str,
    page_format_func: Callable[[PageFormatContext[T]], str] = join_page_data_func(),
    always_show_pagination: bool = False,
    start_from_last_page: bool = False,
    metadata: str | Callable[[int], str] = "",
    empty_list_placeholder: str = "Список пуст",
):
    length = len(data)
    if length <= page_size or page is None:
        page = get_pages_count(length, page_size) - 1 if start_from_last_page else 0

    start_index = page * page_size
    last_index = min(length - 1, start_index + page_size - 1)

    def format_page(data):
        if len(data) == 0:
            return empty_list_placeholder

        if page_format_func is not None:
            return page_format_func(
                PageFormatContext(
                    data=data[start_index : last_index + 1],
                    page_items_range=(start_index, last_index),
                )
            )

    return (
        ("" if list_header is None else f"{str(list_header)}\n\n") + format_page(data),
        create_pagination_keyboard(
            unique_keyboard_name,
            current_page=page,
            pages_count=get_pages_count(length, page_size),
            metadata=metadata,
        )
        if length > page_size or always_show_pagination
        else None,
    )


class Paginator[T]:
    def __init__(
        self,
        unique_keyboard_name: str,
        list_header: str | None,
        page_size: int,
        data_func: Callable[[], list[T]] = lambda: [],
        page_format_func: Callable[[PageFormatContext[T]], str] = join_page_data_func(),
        always_show_pagination: bool = True,
        delimiter: str = "\n",
        start_from_last_page: bool = False,
        keyboard_decorator: Callable[
            [list[InlineKeyboardButton]],
            list[list[InlineKeyboardButton]],
        ] = lambda x: [x],
        metadata: str | Callable[[int], str] = "",
    ):
        self.unique_keyboard_name = unique_keyboard_name
        self.list_header = list_header
        self.page_size = page_size
        self.data_func = data_func
        self.page_format_func = page_format_func
        self.always_show_pagination = always_show_pagination
        self.delimiter = delimiter
        self.start_from_last_page = start_from_last_page
        self.keyboard_decorator = keyboard_decorator
        self.metadata = metadata

    async def show_list(self, update: Update):
        text, keyboard = self._get_data_page()
        await update.message.reply_text(
            text=text,
            parse_mode="markdown",
            reply_markup=InlineKeyboardMarkup(self.keyboard_decorator(keyboard)),
        )
        return True

    async def process_callback(self, update: Update):
        parsed = parse_and_validate_keyboard(
            self.unique_keyboard_name,
            update.callback_query.data,
            parse_func=parse_pagination,
        )

        return await self.process_parsed_callback(update, parsed)

    async def process_parsed_callback(
        self, update: Update, parsed: PaginationParseResult | None
    ):
        if parsed is None:
            return False

        if not parsed.is_current_page:
            text, keyboard = self._get_data_page(parsed.page_number)
            await update.callback_query.message.edit_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(self.keyboard_decorator(keyboard)),
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
            page_format_func=self.page_format_func,
            always_show_pagination=self.always_show_pagination,
            start_from_last_page=self.start_from_last_page,
            metadata=self.metadata,
        )
