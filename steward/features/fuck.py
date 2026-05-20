from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from io import BytesIO

from PIL import Image, ImageDraw
from pyrate_limiter import BucketFullException
from telegram import InputFile, Message, MessageEntity

from steward.data.models.fuck_asset import FuckAsset
from steward.data.models.user import User
from steward.data.repository import Repository
from steward.framework import Feature, FeatureContext, collection, subcommand
from steward.helpers.avatars import get_avatar_image
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.media import fetch_tg_file_bytes

logger = logging.getLogger(__name__)

ASSETS_DIR = Path("data/fuck")
MAX_OUTPUT_DIM = 480

_COMPOSE_SEMAPHORE = asyncio.Semaphore(2)
_USER_RATE_LIMIT = 2
_USER_RATE_WINDOW = Duration.MINUTE


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


def _compose_mp4(
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

    # Avatar art rarely needs to be larger than the output. Resize once upfront.
    avatar_a = _shrink_avatar(avatar_a)
    avatar_b = _shrink_avatar(avatar_b)

    composited: list[Image.Image] = []
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
        composited.append(bg)

    # libx264 needs even dimensions
    w0, h0 = composited[0].size
    even = (w0 - (w0 % 2), h0 - (h0 % 2))
    if even != (w0, h0):
        composited = [img.resize(even, Image.LANCZOS) for img in composited]
    w, h = even

    total_ms = sum(durations) or 1
    # Exact fraction preserves the original timing without rounding drift.
    fps_str = f"{len(durations) * 1000}/{total_ms}"

    raw = b"".join(img.tobytes() for img in composited)
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo",
            "-pixel_format", "rgb24",
            "-video_size", f"{w}x{h}",
            "-framerate", fps_str,
            "-i", "-",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "26",
            "-preset", "veryfast",
            "-movflags", "+faststart",
            str(output_path),
        ],
        input=raw,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[:500]}")


def _shrink_avatar(img: Image.Image) -> Image.Image:
    """Downscale avatar to at most MAX_OUTPUT_DIM on a side — bigger is wasted work."""
    if max(img.size) <= MAX_OUTPUT_DIM:
        return img
    scale = MAX_OUTPUT_DIM / max(img.size)
    return img.resize(
        (int(img.width * scale), int(img.height * scale)),
        Image.LANCZOS,
    )


class FuckFeature(Feature):
    command = "fuck"
    description = "Сгенерить гифку насилия в адрес упомянутого"
    help_examples = ["/fuck @user"]

    users = collection("users")

    @subcommand("", description="Ответом — на сообщение цели или с прикреплённым фото")
    async def do_reply(self, ctx: FeatureContext):
        photo_avatar = await self._photo_from_attachment(ctx.message)
        if photo_avatar is not None:
            await self._run_with_target_avatar(ctx, photo_avatar)
            return
        target = await self._resolve_target(ctx, identifier=None)
        if target is None:
            await ctx.reply(
                "Укажи жертву: /fuck @username, ответом на сообщение "
                "или прикрепи фото"
            )
            return
        target_id, target_name = target
        await self._run(ctx, target_id, target_name)

    @subcommand("<target:rest>", description="@user, id или username без @")
    async def do(self, ctx: FeatureContext, target: str):
        identifier = target.strip().split()[0] if target.strip() else ""
        resolved = await self._resolve_target(ctx, identifier=identifier)
        if resolved is None:
            await ctx.reply(f"Не нашёл {identifier}. Либо имя без @ скрыто, либо такого юзера нет.")
            return
        target_id, target_name = resolved
        await self._run(ctx, target_id, target_name)

    async def _run_with_target_avatar(
        self, ctx: FeatureContext, target_avatar: Image.Image
    ) -> None:
        msg = ctx.message
        if msg is not None and msg.from_user is not None:
            self._remember_user(
                msg.from_user.id, msg.from_user.username, msg.from_user.first_name
            )
        author_name = self._display_name(ctx.user_id)
        await self._compose_and_send(
            ctx,
            ctx.user_id,
            author_name,
            target_id=0,
            b_name=None,
            tag="/fuck",
            b_avatar_override=target_avatar,
        )

    async def _photo_from_attachment(self, message: Message | None) -> Image.Image | None:
        if message is None:
            return None
        photo_sizes = getattr(message, "photo", None) or ()
        if not photo_sizes:
            return None
        try:
            file_id = photo_sizes[-1].file_id
            data = await fetch_tg_file_bytes(self.bot, file_id)
            return Image.open(BytesIO(data)).convert("RGBA")
        except Exception as e:
            logger.warning("/fuck: failed to load attached photo: %s", e)
            return None

    async def _run(self, ctx: FeatureContext, target_id: int, target_name: str | None):
        msg = ctx.message
        if msg is not None and msg.from_user is not None:
            self._remember_user(
                msg.from_user.id, msg.from_user.username, msg.from_user.first_name
            )
        author_name = self._display_name(ctx.user_id)
        await self._compose_and_send(
            ctx,
            ctx.user_id,
            author_name,
            target_id,
            target_name or self._display_name(target_id),
            tag="/fuck",
        )

    async def _compose_and_send(
        self,
        ctx: FeatureContext,
        a_id: int,
        a_name: str | None,
        b_id: int,
        b_name: str | None,
        *,
        tag: str,
        a_avatar_override: Image.Image | None = None,
        b_avatar_override: Image.Image | None = None,
    ) -> None:
        try:
            check_limit(
                f"fuck_compose_{ctx.user_id}", _USER_RATE_LIMIT, _USER_RATE_WINDOW
            )
        except BucketFullException:
            await ctx.reply("Слишком часто. Не больше 2 в минуту, остынь.")
            return

        asset = await asyncio.to_thread(_pick_random_asset, self.repository, ctx.chat_id)
        if asset is None:
            total = len(self.repository.db.fuck_assets)
            logger.warning(
                "%s: no visible asset for chat=%s; total in DB=%s",
                tag, ctx.chat_id, total,
            )
            await ctx.reply(
                f"Нет доступных ассетов для этого чата (всего в базе: {total})."
            )
            return
        source_path, annotation = asset

        async with _COMPOSE_SEMAPHORE:
            a_avatar = a_avatar_override or await get_avatar_image(
                self.bot, a_id, name_hint=a_name
            )
            b_avatar = b_avatar_override or await get_avatar_image(
                self.bot, b_id, name_hint=b_name
            )

            try:
                with tempfile.TemporaryDirectory(prefix="fuck_") as tmp_dir:
                    output_path = Path(tmp_dir) / "fuck.mp4"
                    await asyncio.to_thread(
                        _compose_mp4,
                        source_path,
                        annotation,
                        a_avatar,
                        b_avatar,
                        output_path,
                    )
                    with output_path.open("rb") as f:
                        await self.bot.send_animation(
                            chat_id=ctx.chat_id,
                            animation=InputFile(f, filename="fuck.mp4"),
                        )
            except Exception as e:
                logger.exception("Failed to compose %s gif: %s", tag, e)
                await ctx.reply("Не получилось сгенерить, попробуй позже")

    def _user(self, user_id: int) -> User | None:
        return next((u for u in self.repository.db.users if u.id == user_id), None)

    def _display_name(self, user_id: int) -> str | None:
        u = self._user(user_id)
        if u is None:
            return None
        return u.first_name or u.username

    def _remember_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
    ) -> bool:
        u = self._user(user_id)
        changed = False
        if u is None:
            self.users.add(User(user_id, username, [], first_name=first_name))
            return True
        if username and u.username != username:
            u.username = username
            changed = True
        if first_name and u.first_name != first_name:
            u.first_name = first_name
            changed = True
        return changed

    async def _resolve_target(
        self, ctx: FeatureContext, identifier: str | None
    ) -> tuple[int, str | None] | None:
        msg = ctx.message
        if msg is not None:
            reply = msg.reply_to_message
            if reply is not None and reply.from_user is not None:
                u = reply.from_user
                if self._remember_user(u.id, u.username, u.first_name):
                    await self.users.save()
                return u.id, self._display_name(u.id)
            for ent in (msg.entities or ()):
                if ent.type == MessageEntity.TEXT_MENTION and ent.user is not None:
                    u = ent.user
                    if self._remember_user(u.id, u.username, u.first_name):
                        await self.users.save()
                    return u.id, self._display_name(u.id)
        if not identifier:
            return None
        ident = identifier.lstrip("@")
        try:
            target_id = int(ident)
        except ValueError:
            target_id = None
        if target_id is not None:
            return target_id, self._display_name(target_id)

        user = self.users.find_one(
            lambda u: u.username and u.username.lower() == ident.lower()
        )
        if user is not None:
            return user.id, self._display_name(user.id)

        return await self._lookup_by_username(ident)

    async def _lookup_by_username(self, username: str) -> tuple[int, str | None] | None:
        try:
            chat = await self.bot.get_chat(f"@{username}")
        except Exception as e:
            logger.info("/fuck: get_chat(@%s) failed: %s", username, e)
            return None
        if getattr(chat, "type", None) != "private":
            return None
        target_id = int(chat.id)
        if self._remember_user(target_id, chat.username, chat.first_name):
            await self.users.save()
        try:
            from steward.helpers.avatars import save_photo_from_file_id
            photo = getattr(chat, "photo", None)
            file_id = getattr(photo, "big_file_id", None) if photo else None
            if file_id:
                await save_photo_from_file_id(self.bot, target_id, file_id)
        except Exception as e:
            logger.info("/fuck: caching avatar for @%s failed: %s", username, e)
        return target_id, self._display_name(target_id)


class SexFeature(FuckFeature):
    command = "sex"
    description = "Сгенерить гифку насилия между двумя пользователями"
    help_examples = ["/sex @author @target"]

    @subcommand(
        "<a:str> <b:str>",
        description="@a, @b — два пользователя (id, username или @user)",
    )
    async def do_pair(self, ctx: FeatureContext, a: str, b: str):
        ra = await self._resolve_target_arg(a)
        if ra is None:
            await ctx.reply(f"Не нашёл {a}. Либо приватность, либо нет такого юзера.")
            return
        rb = await self._resolve_target_arg(b)
        if rb is None:
            await ctx.reply(f"Не нашёл {b}. Либо приватность, либо нет такого юзера.")
            return
        a_id, a_name = ra
        b_id, b_name = rb
        await self._compose_and_send(ctx, a_id, a_name, b_id, b_name, tag="/sex")

    @subcommand(
        "",
        description="Прикрепи фото + ответом на сообщение с фото — два фото = два «участника»",
    )
    async def do_reply(self, ctx: FeatureContext):
        if await self._try_photos(ctx):
            return
        await ctx.reply(
            "Юзай так: /sex @author @target — либо прикрепи фото и ответь "
            "на сообщение с другим фото"
        )

    @subcommand("<args:rest>", description="Нужны два аргумента")
    async def do(self, ctx: FeatureContext, args: str):
        if await self._try_photos(ctx):
            return
        await ctx.reply("Юзай так: /sex @author @target")

    async def _try_photos(self, ctx: FeatureContext) -> bool:
        msg = ctx.message
        if msg is None:
            return False
        own = await self._photo_from_attachment(msg)
        reply_msg = getattr(msg, "reply_to_message", None)
        replied = await self._photo_from_attachment(reply_msg)
        if own is None or replied is None:
            return False
        await self._compose_and_send(
            ctx,
            a_id=0,
            a_name=None,
            b_id=0,
            b_name=None,
            tag="/sex",
            a_avatar_override=own,
            b_avatar_override=replied,
        )
        return True

    async def _resolve_target_arg(self, ident: str) -> tuple[int, str | None] | None:
        ident = ident.strip().lstrip("@")
        if not ident:
            return None
        try:
            uid = int(ident)
            return uid, self._display_name(uid)
        except ValueError:
            pass
        user = self.users.find_one(
            lambda u: u.username and u.username.lower() == ident.lower()
        )
        if user is not None:
            return user.id, self._display_name(user.id)
        return await self._lookup_by_username(ident)
