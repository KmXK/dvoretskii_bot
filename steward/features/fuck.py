from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from io import BytesIO

from PIL import Image
from pyrate_limiter import BucketFullException
from telegram import InputFile, Message, MessageEntity

from steward.data.models.fuck_asset import FuckAsset
from steward.data.models.user import User
from steward.data.repository import Repository
from steward.framework import Feature, FeatureContext, collection, subcommand
from steward.helpers.avatars import get_avatar_image
from steward.helpers.fuck_render_job import (
    MIN_AVAILABLE_MEMORY_BYTES,
    available_memory_bytes,
    run_render_job,
)
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.media import fetch_tg_file_bytes

logger = logging.getLogger(__name__)

ASSETS_DIR = Path("data/fuck")
_COMPOSE_LOCK = asyncio.Lock()
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


def _pick_random_asset(repo: Repository, chat_id: int) -> tuple[FuckAsset, Path, dict[str, Any]] | None:
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
        return asset, media, data
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


class FuckFeature(Feature):
    command = "fuck"
    description = "Сгенерить гифку насилия в адрес упомянутого"
    help_examples = ["/fuck @user"]

    users = collection("users")

    @subcommand("", description="Ответом — на сообщение цели или с прикреплённым фото")
    async def do_reply(self, ctx: FeatureContext):
        if ctx.message is not None and ctx.message.photo:
            await self._run_with_target_photo(ctx, ctx.message)
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

    async def _run_with_target_photo(
        self, ctx: FeatureContext, target_photo: Message
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
            b_id=0,
            b_name=None,
            tag="/fuck",
            b_photo=target_photo,
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

    async def _load_avatar(
        self,
        user_id: int,
        name: str | None,
        photo: Message | None,
    ) -> Image.Image:
        if photo is None:
            return await get_avatar_image(self.bot, user_id, name_hint=name)

        avatar = await self._photo_from_attachment(photo)
        if avatar is None:
            raise RuntimeError("Failed to load attached avatar")

        return avatar

    async def _compose_and_send(
        self,
        ctx: FeatureContext,
        a_id: int,
        a_name: str | None,
        b_id: int,
        b_name: str | None,
        *,
        tag: str,
        a_photo: Message | None = None,
        b_photo: Message | None = None,
    ) -> None:
        request_context = (
            f"request_id={uuid.uuid4().hex} chat_id={ctx.chat_id} "
            f"user_id={ctx.user_id} message_id={getattr(ctx.message, 'message_id', None)}"
        )
        if _COMPOSE_LOCK.locked():
            logger.info("%s rejected: busy %s", tag, request_context)
            await ctx.reply("Генератор занят, попробуй чуть позже")
            return

        async with _COMPOSE_LOCK:
            try:
                available = available_memory_bytes()
            except (OSError, ValueError, RuntimeError):
                logger.exception("%s rejected: memory unavailable %s", tag, request_context)
                await ctx.reply("Генератор временно недоступен, попробуй позже")
                return

            if available < MIN_AVAILABLE_MEMORY_BYTES:
                logger.warning(
                    "%s rejected: low memory %s available_mib=%s",
                    tag,
                    request_context,
                    available // (1024 * 1024),
                )
                await ctx.reply("Сейчас не хватает ресурсов для генерации, попробуй позже")
                return

            try:
                check_limit(f"fuck_compose_{ctx.user_id}", _USER_RATE_LIMIT, _USER_RATE_WINDOW)
            except BucketFullException:
                logger.info("%s rejected: rate limit %s", tag, request_context)
                await ctx.reply("Слишком часто. Не больше 2 в минуту, остынь.")
                return

            selected = _pick_random_asset(self.repository, ctx.chat_id)
            if selected is None:
                total = len(self.repository.db.fuck_assets)
                logger.warning("%s: no visible asset %s total=%s", tag, request_context, total)
                await ctx.reply(f"Нет доступных ассетов для этого чата (всего в базе: {total}).")
                return

            asset, source_path, annotation = selected
            render_context = (
                f"{request_context} asset_id={asset.id} asset_name={asset.name!r} "
                f"source={source_path}"
            )
            started = time.monotonic()
            logger.info(
                "%s render started: %s available_mib=%s",
                tag,
                render_context,
                available // (1024 * 1024),
            )
            try:
                a_avatar = await self._load_avatar(a_id, a_name, a_photo)
                b_avatar = await self._load_avatar(b_id, b_name, b_photo)
                with tempfile.TemporaryDirectory(prefix="fuck_") as tmp_dir:
                    output_path = Path(tmp_dir) / "fuck.mp4"
                    result = await run_render_job(
                        source_path,
                        annotation,
                        a_avatar,
                        b_avatar,
                        output_path,
                    )
                    logger.info(
                        "%s render completed: %s frames=%s dimensions=%sx%s "
                        "duration_ms=%s worker_peak_rss_kib=%s child_peak_rss_kib=%s elapsed_ms=%s",
                        tag,
                        render_context,
                        result["frames"],
                        result["width"],
                        result["height"],
                        result["duration_ms"],
                        result["peak_rss_kib"],
                        result.get("child_peak_rss_kib"),
                        round((time.monotonic() - started) * 1000),
                    )
                    with output_path.open("rb") as file:
                        await self.bot.send_animation(
                            chat_id=ctx.chat_id,
                            animation=InputFile(file, filename="fuck.mp4"),
                        )

                logger.info("%s animation sent: %s", tag, render_context)
            except asyncio.CancelledError:
                logger.info("%s render cancelled: %s", tag, render_context)
                raise
            except TimeoutError:
                logger.warning("%s render timed out: %s", tag, render_context)
                await ctx.reply("Генерация заняла слишком долго, попробуй другой раз")
            except Exception:
                logger.exception("%s render failed: %s", tag, render_context)
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

        reply_msg = getattr(msg, "reply_to_message", None)
        if not msg.photo or reply_msg is None or not reply_msg.photo:
            return False

        await self._compose_and_send(
            ctx,
            a_id=0,
            a_name=None,
            b_id=0,
            b_name=None,
            tag="/sex",
            a_photo=msg,
            b_photo=reply_msg,
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
