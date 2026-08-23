from io import BytesIO

from PIL import Image

from steward.helpers.tennis_image import render_tennis_session_png


def test_render_tennis_session_png_contains_multiple_round_rows():
    raw = render_tennis_session_png(
        session_id=12,
        sport="Настольный теннис",
        date="23.08.2026 18:20",
        player_a="Лёша",
        player_b="Дима",
        wins_a=2,
        wins_b=1,
        rounds=[(11, 7, "Лёша"), (9, 11, "Дима"), (13, 11, "Лёша")],
        duration="24:03",
    )

    image = Image.open(BytesIO(raw))
    assert image.format == "PNG"
    assert image.width == 880
    assert image.height > 500
