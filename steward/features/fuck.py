from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import shutil
import tempfile
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from telegram import InputFile, MessageEntity
from telegram.ext import ExtBot

from steward.data.models.fuck_asset import FuckAsset
from steward.data.repository import Repository
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


_MEDIA_EXTS = ("webp", "gif", "mp4", "webm", "mov")


def _asset_files(asset: FuckAsset) -> tuple[Path, Path]:
    base = ASSETS_DIR / str(asset.owner_id)
    return base / f"{asset.id}.{asset.extension}", base / f"{asset.id}.json"


def _user_in_chat(repo: Repository, user_id: int, chat_id: int) -> bool:
    user = next((u for u in repo.db.users if u.id == user_id), None)
    return bool(user and chat_id in (user.chat_ids or []))


def _visible_assets(repo: Repository, chat_id: int) -> list[FuckAsset]:
    out = []
    for a in repo.db.fuck_assets:
        if a.scope == "global":
            out.append(a)
        elif a.scope == "personal" and _user_in_chat(repo, a.owner_id, chat_id):
            out.append(a)
    return out


def _pick_random_asset(repo: Repository, chat_id: int) -> tuple[Path, dict[str, Any]] | None:
    candidates = _visible_assets(repo, chat_id)
    random.shuffle(candidates)
    for asset in candidates:
        media, ann = _asset_files(asset)
        if not media.exists() or not ann.exists():
            logger.warning("Asset %s: missing files (%s, %s)", asset.id, media, ann)
            continue
        try:
            data = json.loads(ann.read_text())
        except Exception as e:
            logger.warning("Asset %s: bad JSON (%s)", asset.id, e)
            continue
        return media, data
    return None


def migrate_legacy_fuck_assets(repo: Repository) -> int:
    """Move flat data/fuck/<name>.{webp,json,...} into data/fuck/<owner_id>/<uuid>.{ext,json}
    and create FuckAsset records. Returns the number of assets migrated.

    Owner: first admin in repo.db.admin_ids. If no admin is configured, the migration
    is skipped (will retry on next start). Existing DB records are left untouched.
    """
    if not ASSETS_DIR.exists():
        return 0
    if not repo.db.admin_ids:
        return 0
    legacy_jsons = [p for p in ASSETS_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".json"]
    if not legacy_jsons:
        return 0
    owner_id = next(iter(repo.db.admin_ids))
    owner_dir = ASSETS_DIR / str(owner_id)
    owner_dir.mkdir(parents=True, exist_ok=True)

    migrated = 0
    for json_path in legacy_jsons:
        stem = json_path.stem
        media_src = None
        for ext in _MEDIA_EXTS:
            candidate = json_path.with_suffix(f".{ext}")
            if candidate.exists():
                media_src = candidate
                break
        if media_src is None:
            logger.warning("Skipping legacy fuck asset %s: no media sibling", json_path)
            continue
        asset_id = uuid.uuid4().hex
        media_dst = owner_dir / f"{asset_id}.{media_src.suffix.lstrip('.')}"
        ann_dst = owner_dir / f"{asset_id}.json"
        try:
            shutil.move(str(media_src), media_dst)
            shutil.move(str(json_path), ann_dst)
        except Exception:
            logger.exception("Failed to move legacy fuck asset %s", json_path)
            continue
        repo.db.fuck_assets.append(FuckAsset(
            id=asset_id,
            owner_id=owner_id,
            name=stem,
            scope="global",
            extension=media_src.suffix.lstrip("."),
            created_at=int(time.time()),
        ))
        migrated += 1
        logger.info("Migrated legacy fuck asset '%s' → %s (owner %s)", stem, asset_id, owner_id)
    return migrated


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

        asset = await asyncio.to_thread(_pick_random_asset, self.repository, ctx.chat_id)
        if asset is None:
            total = len(self.repository.db.fuck_assets)
            logger.warning(
                "/fuck: no visible asset for chat=%s; total in DB=%s",
                ctx.chat_id, total,
            )
            await ctx.reply(
                f"Нет доступных ассетов для этого чата (всего в базе: {total})."
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
