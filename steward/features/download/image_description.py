import asyncio
import base64
import html
import logging
import math
import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from steward.helpers.ai import make_yandex_vlm_describe


logger = logging.getLogger(__name__)

_MAX_COLLAGE_IMAGES = 36
_SINGLE_LONG_EDGE = 1024
_COLLAGE_TILE_SIZE = 360
_DESCRIPTION_LIMIT = 220


def _selected_paths(paths: list[Path]) -> list[Path]:
    if len(paths) <= _MAX_COLLAGE_IMAGES:
        return paths
    step = (len(paths) - 1) / (_MAX_COLLAGE_IMAGES - 1)
    return [paths[round(index * step)] for index in range(_MAX_COLLAGE_IMAGES)]


def _open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def _single_image(image: Image.Image) -> Image.Image:
    image.thumbnail((_SINGLE_LONG_EDGE, _SINGLE_LONG_EDGE))
    return image


def _collage(images: list[Image.Image]) -> Image.Image:
    columns = math.ceil(math.sqrt(len(images)))
    rows = math.ceil(len(images) / columns)
    collage = Image.new(
        "RGB",
        (columns * _COLLAGE_TILE_SIZE, rows * _COLLAGE_TILE_SIZE),
        (24, 24, 24),
    )
    for index, image in enumerate(images):
        fitted = ImageOps.contain(
            image,
            (_COLLAGE_TILE_SIZE - 8, _COLLAGE_TILE_SIZE - 8),
        )
        column = index % columns
        row = index // columns
        x = column * _COLLAGE_TILE_SIZE + (_COLLAGE_TILE_SIZE - fitted.width) // 2
        y = row * _COLLAGE_TILE_SIZE + (_COLLAGE_TILE_SIZE - fitted.height) // 2
        collage.paste(fitted, (x, y))
    return collage


def _vlm_image(paths: list[Path]) -> bytes:
    selected = _selected_paths(paths)
    images = [_open_rgb(path) for path in selected]
    image = _single_image(images[0]) if len(images) == 1 else _collage(images)
    output = BytesIO()
    image.save(output, format="JPEG", quality=82, optimize=True)
    return output.getvalue()


def _vlm_prompt(image_count: int) -> str:
    if image_count == 1:
        source = "Это одна картинка из поста."
    else:
        source = (
            f"Это коллаж из {image_count} картинок одного поста. "
            "Воспринимай их как одну карусель."
        )
    return (
        f"{source} Опиши содержание одной очень короткой фразой по-русски. "
        "Только суть или смысл шутки, без воды, вступлений и кавычек. "
        "Не переписывай весь текст с картинок; упоминай его только если без него "
        "нельзя понять смысл."
    )


def _clean_description(value: str) -> str | None:
    clean = " ".join((value or "").split()).strip(" \"'«»")
    if not clean:
        return None
    if len(clean) > _DESCRIPTION_LIMIT:
        clean = clean[: _DESCRIPTION_LIMIT - 1].rstrip() + "…"
    return clean


async def describe_image_files(paths: list[Path]) -> str | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    if not os.environ.get("AI_KEY_SECRET") or not os.environ.get("AI_MODEL_VLM"):
        logger.info("image VLM skipped: configuration is missing")
        return None

    try:
        image_bytes = await asyncio.to_thread(_vlm_image, existing)
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")
        description = await make_yandex_vlm_describe(
            0,
            _vlm_prompt(len(existing)),
            [encoded],
            max_tokens=80,
        )
        return _clean_description(description)
    except Exception as error:
        logger.exception("image VLM description failed: %s", error)
        return None


def append_image_description(
    caption: str | None,
    description: str | None,
) -> str | None:
    if not description:
        return caption
    visual = f"<i>🖼 {html.escape(description)}</i>"
    return f"{visual}\n\n{caption}" if caption else visual
