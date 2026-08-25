from colorsys import hsv_to_rgb
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from math import ceil

from PIL import Image, ImageDraw, ImageFont

from steward.helpers.curse_streak import hourly_curse_counts, participant_ids_in_chat


_BG = (18, 18, 18)
_CARD = (30, 30, 30)
_BORDER = (54, 54, 54)
_GRID = (65, 65, 65)
_WHITE = (240, 240, 240)
_MUTED = (155, 155, 155)
_GOLD = (214, 178, 112)

_FONT_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
_FONT_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


@dataclass(frozen=True)
class CurseChartSeries:
    user_id: int
    label: str
    hourly_counts: tuple[int, ...]

    @property
    def cumulative_counts(self) -> tuple[int, ...]:
        total = 0
        result = []
        for count in self.hourly_counts:
            total += count
            result.append(total)
        return tuple(result)

    @property
    def total(self) -> int:
        return sum(self.hourly_counts)


def _font(size: int, *, bold: bool = False):
    for path in (_FONT_BOLD if bold else _FONT_REGULAR):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _user_label(repository, user_id: int) -> str:
    user = next((user for user in repository.db.users if user.id == user_id), None)
    if user is None:
        return str(user_id)
    if user.username:
        return f"@{user.username}"
    return user.first_name or str(user_id)


def build_curse_chart_series(repository, chat_id: int, day: date) -> list[CurseChartSeries]:
    return [
        CurseChartSeries(
            user_id=user_id,
            label=_user_label(repository, user_id),
            hourly_counts=tuple(hourly_curse_counts(repository, user_id, day)),
        )
        for user_id in participant_ids_in_chat(repository, chat_id)
    ]


def _series_color(index: int, total: int) -> tuple[int, int, int]:
    hue = (index / max(total, 1) + 0.04) % 1.0
    red, green, blue = hsv_to_rgb(hue, 0.68, 0.95)
    return int(red * 255), int(green * 255), int(blue * 255)


def _ellipsize(draw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def render_curse_chart_png(
    series: list[CurseChartSeries],
    day: date,
    *,
    width: int = 1200,
) -> bytes | None:
    if not series:
        return None

    legend_columns = min(3, len(series))
    legend_rows = ceil(len(series) / legend_columns)
    height = 760 + legend_rows * 52
    image = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (24, 24, width - 24, height - 24),
        radius=28,
        fill=_CARD,
        outline=_BORDER,
        width=2,
    )

    title_font = _font(36, bold=True)
    subtitle_font = _font(23)
    axis_font = _font(19)
    legend_font = _font(22, bold=True)
    draw.text(
        (58, 50),
        f"Маты за {day.day} {_MONTHS[day.month - 1]}",
        font=title_font,
        fill=_WHITE,
    )
    draw.text(
        (58, 98),
        "Накопительно по часам · 24 точки на человека",
        font=subtitle_font,
        fill=_MUTED,
    )

    left = 86
    right = width - 54
    top = 160
    bottom = 650
    plot_width = right - left
    plot_height = bottom - top
    maximum = max(max(item.cumulative_counts) for item in series)
    y_top = max(5, ceil(maximum / 5) * 5)

    for tick in range(6):
        value = y_top * tick // 5
        y = bottom - plot_height * tick / 5
        draw.line((left, y, right, y), fill=_GRID, width=1)
        label = str(value)
        label_width = draw.textlength(label, font=axis_font)
        draw.text((left - label_width - 14, y - 11), label, font=axis_font, fill=_MUTED)

    for hour in range(24):
        x = left + plot_width * hour / 23
        if hour % 2 == 0 or hour == 23:
            draw.line((x, top, x, bottom), fill=_GRID, width=1)
            label = f"{hour:02d}"
            label_width = draw.textlength(label, font=axis_font)
            draw.text((x - label_width / 2, bottom + 14), label, font=axis_font, fill=_MUTED)

    colors = [_series_color(index, len(series)) for index in range(len(series))]
    for item, color in zip(series, colors):
        points = [
            (
                left + plot_width * hour / 23,
                bottom - plot_height * value / y_top,
            )
            for hour, value in enumerate(item.cumulative_counts)
        ]
        draw.line(points, fill=color, width=4, joint="curve")
        for x, y in points:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)

    legend_top = 710
    column_width = (width - 116) / legend_columns
    for index, (item, color) in enumerate(zip(series, colors)):
        row = index // legend_columns
        column = index % legend_columns
        x = 58 + column * column_width
        y = legend_top + row * 52
        draw.line((x, y + 14, x + 34, y + 14), fill=color, width=5)
        label = _ellipsize(
            draw,
            f"{item.label} · {item.total}",
            legend_font,
            int(column_width - 54),
        )
        draw.text((x + 46, y), label, font=legend_font, fill=_WHITE)

    draw.text(
        (58, height - 62),
        "Дворецкий · /curse",
        font=subtitle_font,
        fill=_GOLD,
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
