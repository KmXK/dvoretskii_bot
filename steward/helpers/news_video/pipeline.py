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
from .tts import synthesize_per_sentence

logger = logging.getLogger(__name__)

CHROMA_BBOX = (637, 185, 1110, 460)
ASSETS = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "news"
EMOTIONS_DIR = ASSETS / "anchor_emotions"


def _emotion_anchor(emotion: str, fallback: Path) -> Path:
    """Pick the per-emotion anchor cutout if available, else fall back to neutral/static."""
    p = EMOTIONS_DIR / f"{emotion}.png"
    if p.exists():
        return p
    n = EMOTIONS_DIR / "neutral.png"
    if n.exists():
        return n
    return fallback

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
    tts = await synthesize_per_sentence(
        [[sent.text for sent in s.sentences] for s in script.slides],
        audio_path,
    )
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
    sentence_durations = tts.sentence_durations or [[d] for d in tts.chunk_durations]
    kept: list[tuple[int, Path, float, list[float]]] = []  # (orig_idx, path, dur, sent_durs)
    for orig_idx, (slide, path, dur, sent_durs) in enumerate(
        zip(script.slides, image_results, tts.chunk_durations, sentence_durations)
    ):
        if path is not None:
            kept.append((orig_idx, path, dur, sent_durs))
    if not kept:
        logger.error("no slide images obtained")
        return None

    filtered_paths = [k[1] for k in kept]
    filtered_texts = [script.slides[k[0]].text for k in kept]
    filtered_durations = [k[2] for k in kept]

    # Build per-sentence anchor events with absolute timings.
    anchor_events: list[tuple[Path, float, float]] = []
    cursor = 0.0
    for (orig_idx, _path, slide_dur, sent_durs) in kept:
        slide = script.slides[orig_idx]
        # Sentences and their durations align 1-to-1.
        # If any rounding drift, the last sentence absorbs it so anchor covers the whole slide.
        diff = slide_dur - sum(sent_durs)
        if abs(diff) > 0.02 and sent_durs:
            sent_durs = list(sent_durs)
            sent_durs[-1] += diff
        for sent, sdur in zip(slide.sentences, sent_durs):
            anchor_p = _emotion_anchor(sent.emotion, anchor_static)
            anchor_events.append((anchor_p, cursor, sdur))
            cursor += sdur

    if animated_anchor is not None:
        logger.info("anchor: animated via EchoMimicV2")
        anchor_arg: Path | list[Path] = animated_anchor
        events_arg = None
    else:
        logger.info(
            "anchor: %d emotion events (emotions=%s)",
            len(anchor_events),
            [sent.emotion for k in kept for sent in script.slides[k[0]].sentences],
        )
        anchor_arg = anchor_static  # unused when anchor_events present
        events_arg = anchor_events

    await progress("compose")
    output_path = out_dir / "news.mp4"
    make_video(
        studio_path=studio_path,
        chroma_bbox=CHROMA_BBOX,
        slide_paths=filtered_paths,
        slide_texts=filtered_texts,
        slide_durations=filtered_durations,
        anchor_path=anchor_arg,
        anchor_events=events_arg,
        audio_path=audio_path,
        output_path=output_path,
        anchor_is_video=animated_anchor is not None,
        workdir=out_dir / "compose",
    )
    return output_path
