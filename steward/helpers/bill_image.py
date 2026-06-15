"""Render a bill's «кто что взял» breakdown as a shareable PNG (PIL).

Used by the web mini-app «поделиться итогом»: the API groups positions per
person (who took what), hands groups here, and the bytes are uploaded to
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


def _font(size: int, bold: bool):
    for candidate in (_FONT_BOLD_CANDIDATES if bold else _FONT_REGULAR_CANDIDATES):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def _ellipsize(draw, text, font, max_w):
    if _text_w(draw, text, font) <= max_w:
        return text
    while text and _text_w(draw, text + "…", font) > max_w:
        text = text[:-1]
    return text + "…"


def render_bill_people_png(
    name: str,
    groups: list[dict],
    *,
    width: int = 880,
) -> bytes:
    """groups: list of {name, total, items:[{label, amount}]}.

    Пусто → «позиции ещё не распределены».
    """
    pad = 48
    title_font = _font(46, bold=True)
    sub_font = _font(26, bold=False)
    person_font = _font(32, bold=True)
    total_font = _font(30, bold=True)
    item_font = _font(26, bold=False)
    amount_font = _font(26, bold=True)
    brand_font = _font(24, bold=True)

    header_h = 168
    footer_h = 70
    person_h = 50
    item_h = 40
    group_gap = 18

    body_h = 0
    if groups:
        for g in groups:
            body_h += person_h + len(g["items"]) * item_h + group_gap
    else:
        body_h = 96
    height = header_h + body_h + footer_h + pad

    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [pad // 2, pad // 2, width - pad // 2, height - pad // 2],
        radius=28, fill=_CARD, outline=_BORDER, width=2,
    )

    x0 = pad
    draw.rounded_rectangle([x0, pad, x0 + 56, pad + 8], radius=4, fill=_GOLD)

    title = _ellipsize(draw, (name or "Счёт").strip(), title_font, width - 2 * pad)
    draw.text((x0, pad + 24), title, font=title_font, fill=_WHITE)
    draw.text((x0, pad + 84), "Кто что взял", font=sub_font, fill=_MUTED)

    y = header_h + pad // 2
    if not groups:
        draw.text((x0, y + 16), "Позиции ещё не распределены", font=person_font, fill=_MUTED)
    else:
        for g in groups:
            total_str = g["total"]
            tw = _text_w(draw, total_str, total_font)
            person = _ellipsize(draw, g["name"], person_font, width - pad - x0 - tw - 24)
            draw.text((x0, y + 6), person, font=person_font, fill=_WHITE)
            draw.text((width - pad - tw, y + 8), total_str, font=total_font, fill=_GOLD)
            y += person_h
            for it in g["items"]:
                amt = it["amount"]
                aw = _text_w(draw, amt, amount_font)
                label = _ellipsize(draw, it["label"], item_font, width - pad - (x0 + 24) - aw - 20)
                draw.text((x0 + 24, y + 4), label, font=item_font, fill=_MUTED)
                draw.text((width - pad - aw, y + 4), amt, font=amount_font, fill=_WHITE)
                y += item_h
            y += group_gap - 6
            draw.line([x0, y - group_gap // 2, width - pad, y - group_gap // 2], fill=_BORDER, width=1)

    draw.text((x0, height - footer_h), "Дворецкий", font=brand_font, fill=_GOLD)

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
