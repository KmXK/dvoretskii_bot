from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp
from telegram import InputFile

from steward.helpers.avatars import cached_avatar_path, make_letter_avatar
from steward.helpers.media import fetch_tg_file_to

JOBS_DIR = Path("data/fuck_jobs")
ASSETS_DIR = Path("data/fuck")
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 4_000_000

_RENDER_SEMAPHORE = asyncio.Semaphore(1)
_ADMITTED_JOBS = 0
_MAX_ADMITTED_JOBS = 3


def _remove_stale_jobs() -> None:
    cutoff = time.time() - 3600
    for job_dir in JOBS_DIR.iterdir():
        if re.fullmatch(r"[0-9a-f]{32}", job_dir.name) and job_dir.stat().st_mtime < cutoff:
            shutil.rmtree(job_dir, ignore_errors=True)


def _copy_attachment(source: Path, destination: Path) -> None:
    if source.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise ValueError("Картинка слишком большая: максимум 20 МБ.")

    total = 0
    with source.open("rb") as src, destination.open("wb") as dst:
        while chunk := src.read(64 * 1024):
            total += len(chunk)
            if total > MAX_ATTACHMENT_BYTES:
                raise ValueError("Картинка слишком большая: максимум 20 МБ.")

            dst.write(chunk)


def _validate_attachment(media: Any) -> None:
    if (getattr(media, "file_size", None) or 0) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Файл слишком большой: максимум 20 МБ.")

    width = getattr(media, "width", None) or 0
    height = getattr(media, "height", None) or 0
    if width * height > MAX_PIXELS:
        raise ValueError("Разрешение слишком большое: максимум 4 мегапикселя.")


async def _save_avatar(bot, user_id: int, name: str | None, destination: Path) -> None:
    cached = cached_avatar_path(user_id)
    if cached is not None:
        await asyncio.to_thread(_copy_attachment, cached, destination)
        return

    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.photos and photos.photos[0]:
            await fetch_tg_file_to(
                bot,
                photos.photos[0][-1].file_id,
                destination,
                max_bytes=MAX_ATTACHMENT_BYTES,
            )
            return
    except Exception:
        pass

    try:
        chat = await bot.get_chat(user_id)
        photo = getattr(chat, "photo", None)
        if photo is not None:
            await fetch_tg_file_to(
                bot,
                photo.big_file_id,
                destination,
                max_bytes=MAX_ATTACHMENT_BYTES,
            )
            return
    except Exception:
        pass

    make_letter_avatar(user_id, name).save(destination, format="PNG")


async def _save_participant(
    bot,
    user_id: int,
    name: str | None,
    media: Any,
    destination: Path,
) -> None:
    if media is None:
        await _save_avatar(bot, user_id, name, destination)
        return

    _validate_attachment(media)
    await fetch_tg_file_to(
        bot,
        media.file_id,
        destination,
        max_bytes=MAX_ATTACHMENT_BYTES,
    )


async def _render_job(job_id: str) -> None:
    worker_url = os.environ.get("FUCK_RENDERER_URL", "http://fuck-renderer:8091").rstrip("/")
    timeout = aiohttp.ClientTimeout(total=70)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
        try:
            async with session.post(f"{worker_url}/render", json={"job_id": job_id}) as response:
                result = await response.json()
                if response.status != 200:
                    raise ValueError(result.get("error") or "Не получилось сгенерить гифку.")
        except BaseException:
            try:
                async with session.delete(
                    f"{worker_url}/render/{job_id}",
                    timeout=aiohttp.ClientTimeout(total=3),
                ):
                    pass
            except Exception:
                pass

            raise


async def _prepare_and_send(
    ctx,
    source_path: Path,
    annotation: dict,
    a_id: int,
    a_name: str | None,
    b_id: int,
    b_name: str | None,
    a_media: Any,
    b_media: Any,
) -> None:
    for media in (a_media, b_media):
        if media is not None:
            _validate_attachment(media)

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_remove_stale_jobs)
    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()
    try:
        manifest = json.dumps({
            "source": str(source_path.resolve().relative_to(ASSETS_DIR.resolve())),
            "annotation": annotation,
        })
        if len(manifest.encode()) > 64 * 1024:
            raise ValueError("Разметка шаблона слишком большая.")

        (job_dir / "manifest.json").write_text(manifest)
        await _save_participant(ctx.bot, a_id, a_name, a_media, job_dir / "a.media")
        await _save_participant(ctx.bot, b_id, b_name, b_media, job_dir / "b.media")
        await _render_job(job_id)

        output_path = job_dir / "output.mp4"
        if not output_path.is_file() or not 0 < output_path.stat().st_size <= MAX_OUTPUT_BYTES:
            raise ValueError("Не получилось сгенерить гифку допустимого размера.")

        with output_path.open("rb") as output:
            await ctx.bot.send_animation(
                chat_id=ctx.chat_id,
                animation=InputFile(output, filename="fuck.mp4", read_file_handle=False),
                write_timeout=60,
            )
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


async def render_and_send(
    ctx,
    source_path: Path,
    annotation: dict,
    a_id: int,
    a_name: str | None,
    b_id: int,
    b_name: str | None,
    *,
    a_media: Any = None,
    b_media: Any = None,
) -> None:
    global _ADMITTED_JOBS
    if _ADMITTED_JOBS >= _MAX_ADMITTED_JOBS:
        raise ValueError("Рендер занят, попробуй чуть позже.")

    _ADMITTED_JOBS += 1
    try:
        async with asyncio.timeout(180):
            async with _RENDER_SEMAPHORE:
                await _prepare_and_send(
                    ctx,
                    source_path,
                    annotation,
                    a_id,
                    a_name,
                    b_id,
                    b_name,
                    a_media,
                    b_media,
                )
    except TimeoutError:
        raise ValueError("Генерация заняла слишком долго, попробуй другую гифку.") from None
    except aiohttp.ClientError:
        raise ValueError("Рендер временно недоступен, попробуй позже.") from None
    finally:
        _ADMITTED_JOBS -= 1
