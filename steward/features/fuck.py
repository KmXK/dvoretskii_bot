from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from telegram import InputFile, MessageEntity
from telegram.ext import ExtBot

from steward.framework import Feature, FeatureContext, collection, subcommand
from steward.helpers.media import fetch_tg_file_bytes

logger = logging.getLogger(__name__)

ASSETS_DIR = Path("data/fuck")
MAX_OUTPUT_DIM = 480
_FALLBACK_COLORS = [
    (244, 67, 54), (33, 150, 243), (76, 175, 80),
    (255, 152, 0), (156, 39, 176), (0, 188, 212),
    (255, 87, 34), (63, 81, 181),
]


def _list_annotation_files(dir_path: Path) -> list[Path]:
    if not dir_path.exists():
        return []
    return sorted(p for p in dir_path.iterdir() if p.suffix.lower() == ".json")


_MEDIA_EXTS = (".webp", ".gif", ".mp4", ".webm", ".mov")


def _resolve_source(json_path: Path) -> Path | None:
    for ext in _MEDIA_EXTS:
        sibling = json_path.with_suffix(ext)
        if sibling.exists():
            return sibling
    return None


def _pick_random_asset(dir_path: Path) -> tuple[Path, dict[str, Any]] | None:
    candidates = _list_annotation_files(dir_path)
    random.shuffle(candidates)
    for path in candidates:
        source_path = _resolve_source(path)
        if source_path is None:
            logger.warning("Asset %s: no sibling media file with matching name", path)
            continue
        try:
            data = json.loads(path.read_text())
        except Exception as e:
            logger.warning("Skipping %s: bad JSON (%s)", path, e)
            continue
        return source_path, data
    return None


def _lerp(a: float, b: float, r: float) -> float:
    return a + (b - a) * r


def _is_visible(k: dict[str, Any]) -> bool:
    return k.get("visible", True) is not False


def _interpolate(keyframes: list[dict[str, Any]], t: float) -> dict[str, float] | None:
    if not keyframes:
        return None
    if t <= keyframes[0]["t"]:
        return dict(keyframes[0]) if _is_visible(keyframes[0]) else None
    if t >= keyframes[-1]["t"]:
        return dict(keyframes[-1]) if _is_visible(keyframes[-1]) else None
    for k0, k1 in zip(keyframes, keyframes[1:]):
        if k0["t"] <= t <= k1["t"]:
            if not _is_visible(k0):
                return None
            span = k1["t"] - k0["t"]
            r = (t - k0["t"]) / span if span > 0 else 0.0
            return {
                "t": t,
                "x": _lerp(k0["x"], k1["x"], r),
                "y": _lerp(k0["y"], k1["y"], r),
                "w": _lerp(k0["w"], k1["w"], r),
                "h": _lerp(k0["h"], k1["h"], r),
                "angle": _lerp(float(k0.get("angle", 0)), float(k1.get("angle", 0)), r),
            }
    return None


def _load_source_frames(path: Path) -> tuple[list[Image.Image], list[int]]:
    ext = path.suffix.lower()
    if ext in (".gif", ".webp"):
        return _load_pil_animation(path)
    return _load_via_imageio(path)


def _load_pil_animation(path: Path) -> tuple[list[Image.Image], list[int]]:
    frames: list[Image.Image] = []
    durations: list[int] = []
    with Image.open(path) as img:
        n = getattr(img, "n_frames", 1)
        for i in range(n):
            img.seek(i)
            frames.append(img.convert("RGBA").copy())
            durations.append(int(img.info.get("duration", 100) or 100))
    return frames, durations


def _load_via_imageio(path: Path) -> tuple[list[Image.Image], list[int]]:
    import imageio.v3 as iio

    frames = [Image.fromarray(arr).convert("RGBA") for arr in iio.imiter(str(path))]
    try:
        meta = iio.immeta(str(path))
        fps = float(meta.get("fps") or 30)
    except Exception:
        fps = 30.0
    duration_ms = max(1, int(round(1000 / fps)))
    return frames, [duration_ms] * len(frames)


def _draw_avatar_circumscribed(
    frame: Image.Image,
    avatar: Image.Image,
    box: dict[str, float],
) -> None:
    """Draw a circular avatar that circumscribes the bbox (bbox inscribed in circle)."""
    w = max(2.0, float(box["w"]))
    h = max(2.0, float(box["h"]))
    diam = int(math.ceil(math.sqrt(w * w + h * h)))
    cx = float(box["x"]) + w / 2
    cy = float(box["y"]) + h / 2

    a = avatar.resize((diam, diam), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (diam, diam), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diam, diam), fill=255)
    a.putalpha(mask)

    angle = float(box.get("angle", 0) or 0)
    if angle:
        # Annotator/canvas convention: positive angle = clockwise.
        # PIL.rotate is CCW, so negate.
        a = a.rotate(-angle, resample=Image.BICUBIC, expand=True)

    aw, ah = a.size
    tx = int(round(cx - aw / 2))
    ty = int(round(cy - ah / 2))
    frame.alpha_composite(a, (tx, ty))


def _fallback_avatar(seed: int) -> Image.Image:
    color = _FALLBACK_COLORS[seed % len(_FALLBACK_COLORS)]
    size = 256
    img = Image.new("RGBA", (size, size), color + (255,))
    return img


async def _fetch_avatar(bot: ExtBot, user_id: int) -> Image.Image | None:
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
    except Exception as e:
        logger.warning("/fuck get_user_profile_photos(%s) failed: %s", user_id, e)
        return None
    if not photos.photos or not photos.photos[0]:
        logger.info("/fuck no profile photo for user %s", user_id)
        return None
    file_id = photos.photos[0][-1].file_id
    try:
        data = await fetch_tg_file_bytes(bot, file_id)
        return Image.open(BytesIO(data)).convert("RGBA")
    except Exception as e:
        logger.warning("/fuck avatar download failed for %s: %s", user_id, e)
        return None


def _compose_gif(
    source_path: Path,
    annotation: dict[str, Any],
    avatar_a: Image.Image,
    avatar_b: Image.Image,
    output_path: Path,
) -> None:
    frames, durations = _load_source_frames(source_path)
    if not frames:
        raise RuntimeError(f"No frames in {source_path}")
    keyframes_a = annotation.get("keyframes", {}).get("a", [])
    keyframes_b = annotation.get("keyframes", {}).get("b", [])

    out_rgb: list[Image.Image] = []
    cum_ms = 0
    for i, frame in enumerate(frames):
        t = cum_ms / 1000.0
        composite = frame.copy()
        for keyframes, avatar in ((keyframes_a, avatar_a), (keyframes_b, avatar_b)):
            box = _interpolate(keyframes, t)
            if box is None:
                continue
            _draw_avatar_circumscribed(composite, avatar, box)
        cum_ms += durations[i]

        if max(composite.size) > MAX_OUTPUT_DIM:
            scale = MAX_OUTPUT_DIM / max(composite.size)
            new_size = (int(composite.width * scale), int(composite.height * scale))
            composite = composite.resize(new_size, Image.LANCZOS)

        bg = Image.new("RGB", composite.size, (255, 255, 255))
        bg.paste(composite, mask=composite.split()[3])
        out_rgb.append(bg)

    out_rgb[0].save(
        str(output_path),
        save_all=True,
        append_images=out_rgb[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=2,
    )


class FuckFeature(Feature):
    command = "fuck"
    description = "Сгенерить гифку насилия в адрес упомянутого"
    help_examples = ["/fuck @user"]

    users = collection("users")

    @subcommand("", description="Ответом — на сообщение цели")
    async def do_reply(self, ctx: FeatureContext):
        target_id = self._resolve_target(ctx, identifier=None)
        if target_id is None:
            await ctx.reply("Укажи жертву: /fuck @username или ответом на сообщение")
            return
        await self._run(ctx, target_id)

    @subcommand("<target:rest>", description="@user, id или username без @")
    async def do(self, ctx: FeatureContext, target: str):
        identifier = target.strip().split()[0] if target.strip() else ""
        target_id = self._resolve_target(ctx, identifier=identifier)
        if target_id is None:
            await ctx.reply(f"Пользователь {identifier} не найден. Попроси его написать что-нибудь в чат — бот запомнит.")
            return
        await self._run(ctx, target_id)

    async def _run(self, ctx: FeatureContext, target_id: int):

        asset = await asyncio.to_thread(_pick_random_asset, ASSETS_DIR)
        if asset is None:
            resolved = ASSETS_DIR.resolve()
            exists = ASSETS_DIR.exists()
            count = len(_list_annotation_files(ASSETS_DIR)) if exists else 0
            logger.warning(
                "/fuck: no usable asset; dir=%s exists=%s json_count=%s",
                resolved, exists, count,
            )
            await ctx.reply(
                f"Ассеты не найдены в `{ASSETS_DIR}` (exists={exists}, json={count})"
            )
            return
        source_path, annotation = asset

        author_avatar = await _fetch_avatar(self.bot, ctx.user_id) or _fallback_avatar(ctx.user_id)
        target_avatar = await _fetch_avatar(self.bot, target_id) or _fallback_avatar(target_id)

        try:
            with tempfile.TemporaryDirectory(prefix="fuck_") as tmp_dir:
                output_path = Path(tmp_dir) / "fuck.gif"
                await asyncio.to_thread(
                    _compose_gif,
                    source_path,
                    annotation,
                    author_avatar,
                    target_avatar,
                    output_path,
                )
                with output_path.open("rb") as f:
                    await self.bot.send_animation(
                        chat_id=ctx.chat_id,
                        animation=InputFile(f, filename="fuck.gif"),
                    )
        except Exception as e:
            logger.exception("Failed to compose /fuck gif: %s", e)
            await ctx.reply("Не получилось сгенерить, попробуй позже")

    def _resolve_target(self, ctx: FeatureContext, identifier: str | None) -> int | None:
        msg = ctx.message
        if msg is not None:
            reply = msg.reply_to_message
            if reply is not None and reply.from_user is not None:
                return reply.from_user.id
            for ent in (msg.entities or ()):
                if ent.type == MessageEntity.TEXT_MENTION and ent.user is not None:
                    return ent.user.id
        if not identifier:
            return None
        ident = identifier.lstrip("@")
        try:
            return int(ident)
        except ValueError:
            pass
        user = self.users.find_one(
            lambda u: u.username and u.username.lower() == ident.lower()
        )
        return user.id if user else None
