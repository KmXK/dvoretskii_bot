"""Render a bill's final debt distribution as a shareable PNG (PIL).

Used by the web mini-app «поделиться итоговой раскидкой картинкой»: the API
computes net debts, hands rows here, and the resulting bytes are uploaded to
Telegram for a prepared inline message.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# Брендовая палитра «Дворецкий» (ink + gold + green), синхронизирована с web/index.css.
_BG = (18, 18, 18)
_CARD = (30, 30, 30)
_BORDER = (54, 54, 54)
_GOLD = (214, 178, 112)
_WHITE = (240, 240, 240)
_MUTED = (150, 150, 150)
_GREEN = (29, 185, 84)

_FONT_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
_FONT_REGULAR_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def _font(size: int, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (_FONT_BOLD_CANDIDATES if bold else _FONT_REGULAR_CANDIDATES):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def render_bill_summary_png(
    name: str,
    rows: list[tuple[str, str, str]],
    *,
    width: int = 880,
) -> bytes:
    """rows: list of (debtor_name, creditor_name, amount_display). Empty → «все рассчитались»."""
    pad = 48
    title_font = _font(46, bold=True)
    sub_font = _font(26, bold=False)
    name_font = _font(32, bold=True)
    amount_font = _font(32, bold=True)
    brand_font = _font(24, bold=True)

    row_h = 76
    header_h = 168
    footer_h = 70
    body_h = max(row_h, len(rows) * row_h) if rows else 96
    height = header_h + body_h + footer_h + pad

    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)

    # карточка
    draw.rounded_rectangle(
        [pad // 2, pad // 2, width - pad // 2, height - pad // 2],
        radius=28, fill=_CARD, outline=_BORDER, width=2,
    )

    x0 = pad
    # gold-акцент сверху
    draw.rounded_rectangle([x0, pad, x0 + 56, pad + 8], radius=4, fill=_GOLD)

    title = (name or "Счёт").strip()
    if _text_w(draw, title, title_font) > width - 2 * pad:
        while title and _text_w(draw, title + "…", title_font) > width - 2 * pad:
            title = title[:-1]
        title += "…"
    draw.text((x0, pad + 24), title, font=title_font, fill=_WHITE)
    draw.text((x0, pad + 84), "Кто кому должен", font=sub_font, fill=_MUTED)

    y = header_h + pad // 2
    if not rows:
        draw.text((x0, y + 16), "Все рассчитались", font=name_font, fill=_GREEN)
    else:
        for debtor, creditor, amount in rows:
            amount_w = _text_w(draw, amount, amount_font)
            ax = width - pad - amount_w
            # должник → кредитор
            pair = f"{debtor}  →  {creditor}"
            max_pair_w = ax - x0 - 24
            if _text_w(draw, pair, name_font) > max_pair_w:
                while pair and _text_w(draw, pair + "…", name_font) > max_pair_w:
                    pair = pair[:-1]
                pair += "…"
            draw.text((x0, y + 20), pair, font=name_font, fill=_WHITE)
            draw.text((ax, y + 20), amount, font=amount_font, fill=_GREEN)
            y += row_h
            if y < header_h + body_h:
                draw.line([x0, y, width - pad, y], fill=_BORDER, width=1)

    draw.text((x0, height - footer_h), "Дворецкий", font=brand_font, fill=_GOLD)

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
