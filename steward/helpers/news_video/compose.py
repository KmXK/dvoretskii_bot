"""Video composition using MoviePy 2.x: studio bg + slides in chromakey + anchor + subs + audio.

The anchor can be either a static cutout PNG (legacy) or an animated mp4 produced by
EchoMimicV2 on a black background. For the animated case we pre-process the mp4 with
ffmpeg `colorkey` to make the black background transparent before MoviePy reads it.
"""
from __future__ import annotations

import logging
import subprocess
import textwrap
from pathlib import Path
from typing import Sequence

from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

logger = logging.getLogger(__name__)

_FONT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "assets" / "news" / "fonts" / "DejaVuSans-Bold.ttf"
)


def _colorkey_to_mov(src: Path, dst: Path, threshold: int = 32) -> None:
    """Convert V2 mp4 → mov (qtrle) with hard alpha mask.

    Any pixel whose max(R,G,B) < threshold becomes fully transparent; otherwise
    fully opaque. This avoids `colorkey`'s soft-similarity matching which keys
    dark skin tones / shadows along with the actual black background.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-vf",
        f"format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='if(lt(max(r(X,Y)\\,max(g(X,Y)\\,b(X,Y))),{threshold}),0,255)'",
        "-c:v", "qtrle",
        "-an",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"alpha mask failed: {result.stderr[:500]}")


def make_video(
    *,
    studio_path: Path,
    chroma_bbox: tuple[int, int, int, int],
    slide_paths: Sequence[Path],
    slide_texts: Sequence[str],
    anchor_path: Path | Sequence[Path],
    audio_path: Path,
    output_path: Path,
    slide_durations: Sequence[float] | None = None,
    anchor_events: Sequence[tuple[Path, float, float]] | None = None,
    fps: int = 25,
    anchor_height: int = 560,
    anchor_x: int = 60,
    anchor_y_offset: int = 50,
    font: str | None = None,
    anchor_is_video: bool = False,
    workdir: Path | None = None,
):
    """Compose news video.

    Layout: studio.jpg full-frame, slides in chroma_bbox region (one at a time),
    anchor cutout overlaid on the left bottom, per-slide subtitle at bottom center.

    If `slide_durations` is given, each slide's image + subtitle is shown for exactly
    that long (sums to ~audio length) — this is how we sync to TTS timing. Otherwise
    duration is split evenly.
    """
    audio = AudioFileClip(str(audio_path))
    total_duration = float(audio.duration)
    n = len(slide_paths)
    if n == 0:
        raise ValueError("Need at least one slide")
    if slide_durations is not None and len(slide_durations) == n:
        durations = list(slide_durations)
        # Stretch last slide if rounding leaves a tail
        diff = total_duration - sum(durations)
        if abs(diff) > 0.05:
            durations[-1] += diff
    else:
        durations = [total_duration / n] * n
    starts = [sum(durations[:i]) for i in range(n)]

    x0, y0, x1, y1 = chroma_bbox
    chroma_w, chroma_h = x1 - x0, y1 - y0

    studio = ImageClip(str(studio_path)).with_duration(total_duration)
    studio_w, studio_h = studio.size

    # Black mat covering chromakey area, so letterboxed slides show black bars, not green
    chroma_mat = (
        ColorClip(size=(chroma_w, chroma_h), color=(0, 0, 0))
        .with_position((x0, y0))
        .with_duration(total_duration)
    )

    # Slide track — each slide letterboxed into chroma_w x chroma_h, shown for its own duration
    def slide_clip(path: Path, duration: float) -> ImageClip:
        clip = ImageClip(str(path))
        sw, sh = clip.size
        scale = min(chroma_w / sw, chroma_h / sh)
        clip = clip.resized((int(sw * scale), int(sh * scale))).with_duration(duration)
        cx = x0 + (chroma_w - clip.w) // 2
        cy = y0 + (chroma_h - clip.h) // 2
        return clip.with_position((cx, cy))

    slide_clips = []
    for i, path in enumerate(slide_paths):
        sc = slide_clip(path, durations[i]).with_start(starts[i])
        slide_clips.append(sc)

    # Anchor — four modes (in priority order):
    #   1. anchor_is_video=True: animated mp4 from EchoMimicV2 (black bg → alpha)
    #   2. anchor_events given: arbitrary list of (path, start, duration) — used for
    #      per-sentence emotion switches inside a slide
    #   3. anchor_path is a sequence: one cutout per slide
    #   4. anchor_path is a single Path: legacy static cutout
    anchor_pos = (anchor_x, studio_h - anchor_height + anchor_y_offset)
    anchor_clips: list = []
    if anchor_is_video:
        wd = workdir or output_path.parent
        wd.mkdir(parents=True, exist_ok=True)
        anchor_mov = wd / "anchor_alpha.mov"
        _colorkey_to_mov(anchor_path, anchor_mov)  # type: ignore[arg-type]
        anchor_src = VideoFileClip(str(anchor_mov), has_mask=True)
        logger.info("anchor video: src duration=%.2fs, total=%.2fs",
                    anchor_src.duration, total_duration)
        if anchor_src.duration + 0.1 < total_duration:
            n_loops = int(total_duration / anchor_src.duration) + 1
            anchor_full = concatenate_videoclips([anchor_src] * n_loops)
        else:
            anchor_full = anchor_src
        anchor_clips = [
            anchor_full.resized(height=anchor_height)
            .with_position(anchor_pos)
            .with_duration(total_duration)
        ]
    elif anchor_events:
        logger.info("anchor: %d emotion events", len(anchor_events))
        for ap, st, dur in anchor_events:
            anchor_clips.append(
                ImageClip(str(ap), transparent=True)
                .resized(height=anchor_height)
                .with_position(anchor_pos)
                .with_start(st)
                .with_duration(dur)
            )
    elif isinstance(anchor_path, (list, tuple)):
        for i, ap in enumerate(anchor_path):
            anchor_clips.append(
                ImageClip(str(ap), transparent=True)
                .resized(height=anchor_height)
                .with_position(anchor_pos)
                .with_start(starts[i])
                .with_duration(durations[i])
            )
    else:
        anchor_clips = [
            ImageClip(str(anchor_path), transparent=True)
            .resized(height=anchor_height)
            .with_position(anchor_pos)
            .with_duration(total_duration)
        ]

    # Subtitles — pre-wrap explicitly, render with `label` mode, anchor bottom with margin
    subtitle_clips = []
    font_path = font or (str(_FONT_PATH) if _FONT_PATH.exists() else None)
    font_size = 24
    chars_per_line = 42
    sub_bottom_margin = 60
    sub_kwargs = dict(
        font_size=font_size,
        color="white",
        stroke_color="black",
        stroke_width=2,
        method="label",
        text_align="center",
    )
    if font_path:
        sub_kwargs["font"] = font_path
    for i, text in enumerate(slide_texts):
        wrapped = "\n".join(textwrap.wrap(text, width=chars_per_line, break_long_words=False))
        sub = TextClip(text=wrapped, **sub_kwargs)
        # MoviePy can under-report height with stroke; add line_count * stroke_width as safety
        safety = wrapped.count("\n") * 6 + 8
        y_top = max(0, studio_h - sub.h - sub_bottom_margin - safety)
        logger.info("subtitle %d: lines=%d, sub.h=%d, y_top=%d, start=%.2f, dur=%.2f",
                    i, wrapped.count("\n") + 1, sub.h, y_top, starts[i], durations[i])
        sub = (
            sub.with_start(starts[i])
            .with_duration(durations[i])
            .with_position(("center", y_top))
        )
        subtitle_clips.append(sub)

    final = (
        CompositeVideoClip(
            [studio, chroma_mat, *slide_clips, *anchor_clips, *subtitle_clips],
            size=(studio_w, studio_h),
        )
        .with_audio(audio)
        .with_duration(total_duration)
    )

    final.write_videofile(
        str(output_path),
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        threads=2,
        logger=None,
        preset="medium",
    )

    audio.close()
    final.close()
