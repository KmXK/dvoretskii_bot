"""Multi-source Telegram avatar resolution with disk cache.

Order:
1. Disk cache (`data/avatars/<user_id>.{jpg,webp,png}`)
2. `bot.get_user_profile_photos` (respects user privacy)
3. `bot.get_chat(user_id)` photo (sometimes set when profile_photos is empty)
4. Letter fallback rendered to PIL.Image

Cached images are stored when fetched from any source — including from a
mini-app `photo_url` URL (`save_photo_from_url`) and after a `getChat`
resolution by `@username` (`save_photo_from_file_id`).
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
from telegram.ext import ExtBot

from steward.helpers.media import fetch_tg_file_bytes

logger = logging.getLogger(__name__)

AVATAR_DIR = Path("data/avatars")
_AVATAR_EXTS = ("jpg", "jpeg", "webp", "png")

_FALLBACK_COLORS = [
    (229, 115, 115), (186, 104, 200), (149, 117, 205),
    (121, 134, 203), (100, 181, 246), (77, 208, 225),
    (77, 182, 172), (129, 199, 132), (220, 231, 117),
    (255, 213, 79), (255, 167, 38), (161, 136, 127),
]

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def cached_avatar_path(user_id: int) -> Optional[Path]:
    if not AVATAR_DIR.exists():
        return None
    for ext in _AVATAR_EXTS:
        p = AVATAR_DIR / f"{user_id}.{ext}"
        if p.exists():
            return p
    return None


def has_cached_avatar(user_id: int) -> bool:
    return cached_avatar_path(user_id) is not None


def _save_bytes(user_id: int, data: bytes, ext: str) -> Path:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for other in _AVATAR_EXTS:
        if other == ext:
            continue
        stale = AVATAR_DIR / f"{user_id}.{other}"
        if stale.exists():
            stale.unlink(missing_ok=True)
    path = AVATAR_DIR / f"{user_id}.{ext}"
    path.write_bytes(data)
    return path


def _detect_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "jpg"


async def save_photo_from_file_id(bot: ExtBot, user_id: int, file_id: str) -> Optional[Path]:
    try:
        data = await fetch_tg_file_bytes(bot, file_id)
    except Exception as e:
        logger.warning("avatar: download file_id %s for %s failed: %s", file_id, user_id, e)
        return None
    return _save_bytes(user_id, data, _detect_ext(data))


async def save_photo_from_url(user_id: int, url: str) -> Optional[Path]:
    if not url:
        return None
    try:
        from aiohttp import ClientSession, ClientTimeout
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.info("avatar: photo_url %s for %s returned HTTP %s", url, user_id, resp.status)
                    return None
                data = await resp.read()
    except Exception as e:
        logger.warning("avatar: photo_url %s for %s failed: %s", url, user_id, e)
        return None
    if not data:
        return None
    return _save_bytes(user_id, data, _detect_ext(data))


async def try_fetch_from_bot(bot: ExtBot, user_id: int) -> Optional[Path]:
    """Try every Bot API method to obtain a profile photo. Caches on success."""
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.photos and photos.photos[0]:
            file_id = photos.photos[0][-1].file_id
            path = await save_photo_from_file_id(bot, user_id, file_id)
            if path is not None:
                return path
    except Exception as e:
        logger.info("avatar: get_user_profile_photos(%s) failed: %s", user_id, e)

    try:
        chat = await bot.get_chat(user_id)
        photo = getattr(chat, "photo", None)
        file_id = getattr(photo, "big_file_id", None) if photo else None
        if file_id:
            path = await save_photo_from_file_id(bot, user_id, file_id)
            if path is not None:
                return path
    except Exception as e:
        logger.info("avatar: get_chat(%s) failed: %s", user_id, e)

    return None


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _initials(name: Optional[str], user_id: int) -> str:
    if name:
        cleaned = name.strip()
        if cleaned:
            parts = [p for p in cleaned.split() if p]
            if parts:
                return parts[0][0].upper()
    return str(user_id)[:1]


def make_letter_avatar(user_id: int, name: Optional[str] = None, size: int = 256) -> Image.Image:
    color = _FALLBACK_COLORS[user_id % len(_FALLBACK_COLORS)]
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=color + (255,))

    letter = _initials(name, user_id)
    font = _load_font(int(size * 0.5))
    try:
        bbox = draw.textbbox((0, 0), letter, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (size - tw) / 2 - bbox[0]
        ty = (size - th) / 2 - bbox[1]
    except Exception:
        tw, th = draw.textsize(letter, font=font)
        tx = (size - tw) / 2
        ty = (size - th) / 2
    draw.text((tx, ty), letter, font=font, fill=(255, 255, 255, 255))
    return img


def _load_cached_image(user_id: int) -> Optional[Image.Image]:
    path = cached_avatar_path(user_id)
    if path is None:
        return None
    try:
        return Image.open(BytesIO(path.read_bytes())).convert("RGBA")
    except Exception as e:
        logger.warning("avatar: failed to read cached %s: %s", path, e)
        return None


async def get_avatar_image(
    bot: ExtBot,
    user_id: int,
    *,
    name_hint: Optional[str] = None,
) -> Image.Image:
    """Return an avatar image for the user, falling back to letter avatar.

    Tries cache → Bot API. Never raises; returns a letter fallback as a last resort.
    """
    cached = _load_cached_image(user_id)
    if cached is not None:
        return cached
    path = await try_fetch_from_bot(bot, user_id)
    if path is not None:
        try:
            return Image.open(BytesIO(path.read_bytes())).convert("RGBA")
        except Exception as e:
            logger.warning("avatar: failed to read freshly cached %s: %s", path, e)
    return make_letter_avatar(user_id, name_hint)
