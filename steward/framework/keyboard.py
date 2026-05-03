from dataclasses import dataclass
from typing import Callable, Iterable, Sequence, TypeVar

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

T = TypeVar("T")


@dataclass(frozen=True)
class Button:
    text: str
    callback_data: str | None = None
    url: str | None = None
    webapp: str | None = None

    def to_telegram(self) -> InlineKeyboardButton:
        if self.url:
            return InlineKeyboardButton(self.text, url=self.url)
        if self.webapp:
            return InlineKeyboardButton(self.text, web_app=WebAppInfo(url=self.webapp))
        return InlineKeyboardButton(self.text, callback_data=self.callback_data)


class Keyboard:
    def __init__(self, rows: list[list[Button]]):
        self._rows = rows

    def to_markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[btn.to_telegram() for btn in row] for row in self._rows]
        )

    @property
    def rows(self) -> list[list[Button]]:
        return self._rows

    @staticmethod
    def row(*buttons: Button) -> "Keyboard":
        return Keyboard([list(buttons)])

    @staticmethod
    def column(*buttons: Button) -> "Keyboard":
        return Keyboard([[b] for b in buttons])

    @staticmethod
    def grid(rows: Sequence[Sequence[Button]]) -> "Keyboard":
        return Keyboard([list(row) for row in rows])

    @staticmethod
    def from_items(
        items: Iterable[T],
        button_func: Callable[[T], Button],
        per_row: int = 1,
    ) -> "Keyboard":
        items_list = list(items)
        rows: list[list[Button]] = []
        for i in range(0, len(items_list), per_row):
            rows.append([button_func(x) for x in items_list[i : i + per_row]])
        return Keyboard(rows)

    def append_row(self, *buttons: Button) -> "Keyboard":
        self._rows.append(list(buttons))
        return self

    def prepend_row(self, *buttons: Button) -> "Keyboard":
        self._rows.insert(0, list(buttons))
        return self

    def extend(self, other: "Keyboard | None") -> "Keyboard":
        if other is not None:
            self._rows.extend(other._rows)
        return self

    @staticmethod
    def join(*keyboards: "Keyboard | None") -> "Keyboard":
        result = Keyboard([])
        for kb in keyboards:
            if kb is not None:
                result._rows.extend(kb._rows)
        return result

    @staticmethod
    def from_telegram_buttons(buttons: list[InlineKeyboardButton]) -> "Keyboard":
        result = Keyboard([])
        for b in buttons:
            result._rows.append([
                Button(
                    text=b.text,
                    callback_data=b.callback_data,
                    url=b.url,
                )
            ])
        return result
