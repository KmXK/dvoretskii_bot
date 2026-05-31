"""News-video pipeline orchestrator."""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from .compose import make_video
from .echomimic import animate_anchor
from .images import fetch_slides
from .script import Script, enrich, make_script
from .tts import synthesize_news

logger = logging.getLogger(__name__)

CHROMA_BBOX = (637, 185, 1110, 460)
ASSETS = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "news"

ProgressFn = Callable[[str], Awaitable[None]]


def _echomimic_enabled() -> bool:
    return os.environ.get("NEWS_VIDEO_ECHOMIMIC", "1").lower() not in {"0", "off", "false"}


async def _noop(stage: str) -> None:
    pass


async def generate_news_video(
    *,
    user_id: int,
    source_text: str,
    out_dir: Path,
    progress: ProgressFn = _noop,
) -> Path | None:
    studio_path = ASSETS / "studio.jpg"
    anchor_static = ASSETS / "anchor_cutout.png"
    anchor_for_v2 = ASSETS / "anchor_on_black.jpg"
    if not studio_path.exists() or not anchor_static.exists():
        logger.error("missing assets in %s", ASSETS)
        return None

    await progress("enrich")
    enrich_data = await enrich(user_id, source_text)

    await progress("script")
    script: Script = await make_script(user_id, enrich_data)
    if not script.slides:
        logger.warning("empty script")
        return None
    logger.info("script: %d slides, total chars=%d", len(script.slides), len(script.full_text))

    await progress("tts")
    audio_path = out_dir / "audio.ogg"
    tts = await synthesize_news(script.full_text, audio_path)
    if tts is None:
        logger.error("TTS produced no audio")
        return None

    # Images + anchor animation run in parallel — both take time.
    async def images_task() -> tuple[list[Path], list[str]]:
        slides_dir = out_dir / "slides"
        image_results = await fetch_slides(
            [(s.image_query, s.is_meme) for s in script.slides], slides_dir
        )
        paths: list[Path] = []
        texts: list[str] = []
        for slide, path in zip(script.slides, image_results):
            if path is not None:
                paths.append(path)
                texts.append(slide.text)
        return paths, texts

    async def anchor_task() -> Path | None:
        if not _echomimic_enabled() or not anchor_for_v2.exists():
            return None
        return await animate_anchor(
            image_bytes=anchor_for_v2.read_bytes(),
            audio_chunk_paths=tts.chunk_paths,
            out_dir=out_dir / "anchor",
        )

    await progress("media")
    (images_pair, animated_anchor) = await asyncio.gather(images_task(), anchor_task())
    filtered_paths, filtered_texts = images_pair
    if not filtered_paths:
        logger.error("no slide images obtained")
        return None

    await progress("compose")
    output_path = out_dir / "news.mp4"
    make_video(
        studio_path=studio_path,
        chroma_bbox=CHROMA_BBOX,
        slide_paths=filtered_paths,
        slide_texts=filtered_texts,
        anchor_path=animated_anchor or anchor_static,
        audio_path=audio_path,
        output_path=output_path,
        anchor_is_video=animated_anchor is not None,
        workdir=out_dir / "compose",
    )
    return output_path
