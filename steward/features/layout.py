"""Конверсия раскладки RU↔EN. /layout — превращает «ghbdtn» в «привет»."""

from __future__ import annotations

from steward.framework import Feature, FeatureContext, subcommand


# QWERTY (en) ↔ ЙЦУКЕН (ru). Сравнение посимвольно: каждая буква en соответствует
# букве ru, которая физически находится на той же клавише.
_EN_LAYOUT = (
    "qwertyuiop[]"
    "asdfghjkl;'"
    "zxcvbnm,./"
    "QWERTYUIOP{}"
    'ASDFGHJKL:"'
    "ZXCVBNM<>?"
    "`~"
)
_RU_LAYOUT = (
    "йцукенгшщзхъ"
    "фывапролджэ"
    "ячсмитьбю."
    "ЙЦУКЕНГШЩЗХЪ"
    "ФЫВАПРОЛДЖЭ"
    "ЯЧСМИТЬБЮ,"
    "ёЁ"
)

assert len(_EN_LAYOUT) == len(_RU_LAYOUT), "Layout tables out of sync"

_EN_TO_RU = str.maketrans(_EN_LAYOUT, _RU_LAYOUT)
_RU_TO_EN = str.maketrans(_RU_LAYOUT, _EN_LAYOUT)


def swap_layout(text: str) -> str:
    """Меняет раскладку в обе стороны. Если кириллицы больше — считаем что
    текст случайно набран в кириллице на латинской клавиатуре, и наоборот."""
    cyrillic = sum(1 for c in text if "а" <= c.lower() <= "я" or c.lower() == "ё")
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    if cyrillic > latin:
        return text.translate(_RU_TO_EN)
    return text.translate(_EN_TO_RU)


class LayoutFeature(Feature):
    command = "layout"
    description = "Поменять раскладку (RU↔EN), напр. «ghbdtn» → «привет»"
    help_examples = [
        "/layout — ответом на сообщение",
        "/layout ghbdtn rfr ltkf — конвертировать аргумент",
    ]

    @subcommand("", description="Ответом на сообщение с «кракозябрами»")
    async def from_reply(self, ctx: FeatureContext):
        message = ctx.message
        if message is None:
            return
        reply = message.reply_to_message
        source = (reply.text or reply.caption) if reply else None
        if not source:
            await ctx.reply(
                "Ответь этой командой на сообщение, у которого надо поменять "
                "раскладку — или передай текст: /layout ghbdtn rfr ltkf",
                markdown=False,
            )
            return
        await ctx.reply(swap_layout(source), markdown=False)

    @subcommand("<text:rest>", description="Аргумент — текст для конвертации", catchall=True)
    async def from_arg(self, ctx: FeatureContext, text: str):
        text = text.strip()
        if not text:
            await self.from_reply(ctx)
            return
        await ctx.reply(swap_layout(text), markdown=False)
