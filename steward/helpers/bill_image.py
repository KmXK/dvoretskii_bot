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


def _wrap_text(draw, text, font, max_w):
    lines = []
    line = ""
    for word in str(text).split():
        candidate = f"{line} {word}" if line else word
        if _text_w(draw, candidate, font) <= max_w:
            line = candidate
            continue

        if line:
            lines.append(line)
            line = ""

        for char in word:
            if line and _text_w(draw, line + char, font) > max_w:
                lines.append(line)
                line = ""

            line += char

    return lines + [line or "—"]


def render_bill_people_png(
    name: str,
    groups: list[dict],
    *,
    summary: str = "",
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

    footer_h = 70
    group_gap = 18
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_lines = _wrap_text(measure, name or "Счёт", title_font, width - 2 * pad)
    header_h = pad + 24 + len(title_lines) * 56 + 48 + (40 if summary else 0)
    layouts = []
    body_h = 0
    for group in groups:
        total_w = _text_w(measure, group["total"], total_font)
        person_lines = _wrap_text(measure, group["name"], person_font, width - 2 * pad - total_w - 24)
        person_h = max(50, len(person_lines) * 40 + 10)
        items = []
        for item in group["items"]:
            amount_w = _text_w(measure, item["amount"], amount_font)
            label_lines = _wrap_text(measure, item["label"], item_font, width - 2 * pad - 24 - amount_w - 20)
            detail_lines = _wrap_text(measure, item["detail"], sub_font, width - 2 * pad - 24) if item.get("detail") else []
            item_h = len(label_lines) * 34 + len(detail_lines) * 34 + 12
            items.append((item, amount_w, label_lines, detail_lines, item_h))

        layouts.append((group, total_w, person_lines, person_h, items))
        body_h += person_h + sum(item[-1] for item in items) + group_gap

    if not groups:
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

    title_y = pad + 24
    for line in title_lines:
        draw.text((x0, title_y), line, font=title_font, fill=_WHITE)
        title_y += 56

    draw.text((x0, title_y + 4), "Кто что взял", font=sub_font, fill=_MUTED)
    if summary:
        draw.text((x0, title_y + 44), summary, font=sub_font, fill=_GOLD)

    y = header_h + pad // 2
    if not groups:
        draw.text((x0, y + 16), "Позиции ещё не распределены", font=person_font, fill=_MUTED)
    else:
        for group, total_w, person_lines, person_h, items in layouts:
            for index, line in enumerate(person_lines):
                draw.text((x0, y + 6 + index * 40), line, font=person_font, fill=_WHITE)

            draw.text((width - pad - total_w, y + 8), group["total"], font=total_font, fill=_GOLD)
            y += person_h
            for item, amount_w, label_lines, detail_lines, item_h in items:
                for index, line in enumerate(label_lines):
                    draw.text((x0 + 24, y + 4 + index * 34), line, font=item_font, fill=_WHITE)

                draw.text((width - pad - amount_w, y + 4), item["amount"], font=amount_font, fill=_WHITE)
                detail_y = y + 4 + len(label_lines) * 34
                for line in detail_lines:
                    draw.text((x0 + 24, detail_y), line, font=sub_font, fill=_MUTED)
                    detail_y += 34

                y += item_h

            y += group_gap
            draw.line([x0, y - group_gap // 2, width - pad, y - group_gap // 2], fill=_BORDER, width=1)

    draw.text((x0, height - footer_h), "Дворецкий", font=brand_font, fill=_GOLD)

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
