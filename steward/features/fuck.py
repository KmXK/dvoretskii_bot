from __future__ import annotations

import json
import logging
import random
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from pyrate_limiter import BucketFullException
from telegram import Message, MessageEntity

from steward.data.models.fuck_asset import FuckAsset
from steward.data.models.user import User
from steward.data.repository import Repository
from steward.framework import Feature, FeatureContext, collection, subcommand
from steward.helpers.fuck_jobs import render_and_send
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)

ASSETS_DIR = Path("data/fuck")
_USER_RATE_LIMIT = 2
_USER_RATE_WINDOW = Duration.MINUTE
_MAX_ANNOTATION_BYTES = 64 * 1024


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
            if ann.stat().st_size > _MAX_ANNOTATION_BYTES:
                logger.warning("Asset %s: annotation is too large", asset.id)
                continue
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


def _has_file_id(media: Any) -> bool:
    file_id = getattr(media, "file_id", None)
    return isinstance(file_id, str) and bool(file_id)


def _supported_document(document: Any) -> bool:
    if not _has_file_id(document):
        return False

    mime_type = getattr(document, "mime_type", None)
    file_name = getattr(document, "file_name", None)
    mime_type = mime_type.lower() if isinstance(mime_type, str) else ""
    suffix = Path(file_name).suffix.lower() if isinstance(file_name, str) else ""
    if mime_type == "image/gif":
        return not suffix or suffix == ".gif"
    if mime_type == "video/mp4":
        return not suffix or suffix == ".mp4"
    if mime_type in {"", "application/octet-stream"}:
        return suffix in {".gif", ".mp4"}
    return False


def _media_from_message(message: Message | None) -> Any | None:
    if message is None:
        return None

    photos = getattr(message, "photo", None) or ()
    if photos:
        photo = photos[-1]
        if _has_file_id(photo):
            return photo

    animation = getattr(message, "animation", None)
    if animation is not None and _has_file_id(animation):
        return animation

    document = getattr(message, "document", None)
    if document is not None and _supported_document(document):
        return document

    return None


class FuckFeature(Feature):
    command = "fuck"
    description = "Сгенерить гифку насилия в адрес упомянутого"
    help_examples = ["/fuck @user"]

    users = collection("users")

    @subcommand("", description="Ответом — на сообщение цели или с прикреплённым медиа")
    async def do_reply(self, ctx: FeatureContext):
        target_media = _media_from_message(ctx.message)
        if target_media is None and ctx.message is not None:
            target_media = _media_from_message(getattr(ctx.message, "reply_to_message", None))

        if target_media is not None:
            await self._run_with_target_avatar(ctx, target_media)
            return

        target = await self._resolve_target(ctx, identifier=None)
        if target is None:
            await ctx.reply(
                "Укажи жертву: /fuck @username, ответом на сообщение "
                "или прикрепи фото или гифку"
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

    async def _run_with_target_avatar(self, ctx: FeatureContext, target_media: Any) -> None:
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
            b_media=target_media,
        )

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
        a_media: Any | None = None,
        b_media: Any | None = None,
    ) -> None:
        request_context = (
            f"request_id={uuid.uuid4().hex} chat_id={ctx.chat_id} "
            f"user_id={ctx.user_id} message_id={getattr(ctx.message, 'message_id', None)}"
        )
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
        logger.info("%s render started: %s", tag, render_context)
        try:
            await render_and_send(
                ctx,
                source_path,
                annotation,
                a_id,
                a_name,
                b_id,
                b_name,
                a_media=a_media,
                b_media=b_media,
            )
        except Exception as error:
            if isinstance(error, ValueError):
                logger.warning("%s render rejected: %s %s", tag, render_context, error)
                await ctx.reply(str(error))
                return

            if isinstance(error, TimeoutError):
                logger.warning("%s render timed out: %s", tag, render_context)
                await ctx.reply("Генерация заняла слишком долго, попробуй другой раз")
                return

            logger.exception("%s render failed: %s", tag, render_context)
            await ctx.reply("Не получилось сгенерить, попробуй позже")
            return

        logger.info("%s animation sent: %s", tag, render_context)

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
            reply = getattr(msg, "reply_to_message", None)
            if reply is not None and reply.from_user is not None:
                u = reply.from_user
                if self._remember_user(u.id, u.username, u.first_name):
                    await self.users.save()
                return u.id, self._display_name(u.id)

            for ent in (getattr(msg, "entities", None) or ()):
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

        author_media = _media_from_message(msg)
        target_media = _media_from_message(reply_msg)
        if author_media is None or target_media is None:
            return False

        await self._compose_and_send(
            ctx,
            a_id=0,
            a_name=None,
            b_id=0,
            b_name=None,
            tag="/sex",
            a_media=author_media,
            b_media=target_media,
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
