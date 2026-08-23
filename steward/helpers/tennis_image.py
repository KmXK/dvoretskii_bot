"""Рендер одной теннисной сессии для Telegram shareMessage."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

_BG = (18, 18, 18)
_CARD = (30, 30, 30)
_BORDER = (54, 54, 54)
_GOLD = (214, 178, 112)
_WHITE = (240, 240, 240)
_MUTED = (150, 150, 150)
_WIN = (29, 185, 84)

_FONT_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
_FONT_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


def _font(size: int, *, bold: bool = False):
    for path in (_FONT_BOLD if bold else _FONT_REGULAR):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit(draw, value: str, font, max_width: int) -> str:
    value = str(value)
    if draw.textlength(value, font=font) <= max_width:
        return value
    while value and draw.textlength(value + "…", font=font) > max_width:
        value = value[:-1]
    return value + "…"


def render_tennis_session_png(
    *,
    session_id: int,
    sport: str,
    date: str,
    player_a: str,
    player_b: str,
    wins_a: int,
    wins_b: int,
    rounds: list[tuple[int | None, int | None, str]],
    duration: str | None = None,
    width: int = 880,
) -> bytes:
    """`rounds`: (score_a, score_b, winner_name), по порядку игры."""
    pad = 48
    header_h = 250
    row_h = 62
    footer_h = 78
    body_h = max(92, len(rounds) * row_h + 54)
    height = pad + header_h + body_h + footer_h

    image = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (24, 24, width - 24, height - 24),
        radius=28,
        fill=_CARD,
        outline=_BORDER,
        width=2,
    )

    title_font = _font(30, bold=True)
    score_font = _font(58, bold=True)
    name_font = _font(28, bold=True)
    body_font = _font(25)
    body_bold = _font(25, bold=True)
    small_font = _font(22)

    draw.rounded_rectangle((pad, pad, pad + 64, pad + 8), radius=4, fill=_GOLD)
    draw.text((pad, pad + 26), f"{sport} · сессия #{session_id}", font=title_font, fill=_WHITE)
    meta = date + (f" · {duration}" if duration else "")
    draw.text((pad, pad + 70), meta, font=small_font, fill=_MUTED)

    center = width // 2
    left_name = _fit(draw, player_a, name_font, center - pad - 54)
    right_name = _fit(draw, player_b, name_font, center - pad - 54)
    draw.text((pad, pad + 124), left_name, font=name_font, fill=_WHITE)
    right_w = draw.textlength(right_name, font=name_font)
    draw.text((width - pad - right_w, pad + 124), right_name, font=name_font, fill=_WHITE)
    score = f"{wins_a}:{wins_b}"
    score_w = draw.textlength(score, font=score_font)
    draw.text((center - score_w / 2, pad + 106), score, font=score_font, fill=_GOLD)

    y = pad + header_h
    draw.text((pad, y), "Как играли по партиям", font=body_bold, fill=_WHITE)
    y += 48
    if not rounds:
        draw.text((pad, y), "Сохранён только итоговый счёт", font=body_font, fill=_MUTED)
    for index, (score_a, score_b, winner) in enumerate(rounds, 1):
        if index > 1:
            draw.line((pad, y - 8, width - pad, y - 8), fill=_BORDER, width=1)
        score_text = "—" if score_a is None or score_b is None else f"{score_a}:{score_b}"
        draw.text((pad, y + 8), f"{index}", font=body_font, fill=_MUTED)
        draw.text((pad + 58, y + 8), score_text, font=body_bold, fill=_WHITE)
        winner_text = _fit(draw, f"победил {winner}", body_font, width - pad * 2 - 230)
        draw.text((pad + 210, y + 8), winner_text, font=body_font, fill=_WIN)
        y += row_h

    draw.text((pad, height - footer_h), "Дворецкий · Tennis", font=small_font, fill=_GOLD)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
