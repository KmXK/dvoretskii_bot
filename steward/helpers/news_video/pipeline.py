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
from .tts import synthesize_per_slide

logger = logging.getLogger(__name__)

CHROMA_BBOX = (637, 185, 1110, 460)
ASSETS = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "news"

ProgressFn = Callable[[str], Awaitable[None]]


def _echomimic_enabled() -> bool:
    # Default OFF — Modal $30 free credit requires a card, and the emotion-based
    # static anchor (see assets/news/anchor_emotions/) usually looks good enough.
    # Set NEWS_VIDEO_ECHOMIMIC=1 to opt into the V2 animation when you do have
    # Modal credit.
    return os.environ.get("NEWS_VIDEO_ECHOMIMIC", "0").lower() in {"1", "on", "true"}


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
    tts = await synthesize_per_slide([s.text for s in script.slides], audio_path)
    if tts is None:
        logger.error("TTS produced no audio")
        return None

    # Images + anchor animation run in parallel — both take time.
    async def images_task() -> list[Path | None]:
        slides_dir = out_dir / "slides"
        return await fetch_slides(
            [(s.image_query, s.is_meme) for s in script.slides], slides_dir
        )

    async def anchor_task() -> Path | None:
        if not _echomimic_enabled():
            logger.info("echomimic disabled via NEWS_VIDEO_ECHOMIMIC — using static anchor")
            return None
        if not anchor_for_v2.exists():
            logger.warning("anchor_on_black.jpg missing — using static anchor")
            return None
        return await animate_anchor(
            image_bytes=anchor_for_v2.read_bytes(),
            audio_chunk_paths=tts.chunk_paths,
            out_dir=out_dir / "anchor",
        )

    await progress("media")
    (image_results, animated_anchor) = await asyncio.gather(images_task(), anchor_task())

    # Keep slides aligned to their texts/durations; drop slides whose image fetch failed.
    filtered_paths: list[Path] = []
    filtered_texts: list[str] = []
    filtered_durations: list[float] = []
    for slide, path, dur in zip(script.slides, image_results, tts.chunk_durations):
        if path is not None:
            filtered_paths.append(path)
            filtered_texts.append(slide.text)
            filtered_durations.append(dur)
    if not filtered_paths:
        logger.error("no slide images obtained")
        return None

    if animated_anchor is None:
        logger.info("anchor: static cutout (no animation)")
    else:
        logger.info("anchor: animated via EchoMimicV2")

    await progress("compose")
    output_path = out_dir / "news.mp4"
    make_video(
        studio_path=studio_path,
        chroma_bbox=CHROMA_BBOX,
        slide_paths=filtered_paths,
        slide_texts=filtered_texts,
        slide_durations=filtered_durations,
        anchor_path=animated_anchor or anchor_static,
        audio_path=audio_path,
        output_path=output_path,
        anchor_is_video=animated_anchor is not None,
        workdir=out_dir / "compose",
    )
    return output_path
