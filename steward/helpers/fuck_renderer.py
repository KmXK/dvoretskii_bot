from __future__ import annotations

import json
import math
import resource
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


MAX_OUTPUT_DIM = 480
MAX_PIXELS = 4_194_304
MAX_EDGE = 4096
MAX_FRAMES = 900
MAX_DURATION_MS = 30_000
ADDRESS_SPACE_LIMIT_BYTES = 512 * 1024**2

_PIL_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class _MediaInfo:
    width: int
    height: int
    frame_count: int
    duration_ms: int
    frame_duration_ms: int | None
    pil_source: bool


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


def _draw_avatar_circumscribed(
    frame: Any,
    avatar: Any,
    box: dict[str, float],
) -> None:
    """Draw a circular avatar that circumscribes the bbox (bbox inscribed in circle)."""
    from PIL import Image, ImageDraw

    w = max(2.0, float(box["w"]))
    h = max(2.0, float(box["h"]))
    diam = min(
        int(math.ceil(math.sqrt(w * w + h * h))),
        int(math.ceil(math.sqrt(frame.width * frame.width + frame.height * frame.height))),
    )
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
        rotated = a.rotate(-angle, resample=Image.BICUBIC, expand=True)
        a.close()
        a = rotated

    aw, ah = a.size
    tx = int(round(cx - aw / 2))
    ty = int(round(cy - ah / 2))
    try:
        frame.alpha_composite(a, (tx, ty))
    finally:
        mask.close()
        a.close()


def _shrink_avatar(img: Any) -> Any:
    """Downscale avatar to at most MAX_OUTPUT_DIM on a side — bigger is wasted work."""
    from PIL import Image

    if max(img.size) <= MAX_OUTPUT_DIM:
        return img
    scale = MAX_OUTPUT_DIM / max(img.size)
    return img.resize(
        (int(img.width * scale), int(img.height * scale)),
        Image.LANCZOS,
    )


def _set_address_space_limit() -> None:
    try:
        resource.setrlimit(
            resource.RLIMIT_AS,
            (ADDRESS_SPACE_LIMIT_BYTES, ADDRESS_SPACE_LIMIT_BYTES),
        )
    except (OSError, ValueError) as error:
        raise RenderError("unable to set worker address-space limit") from error


def _path_from_job(job: dict[str, Any], key: str) -> Path:
    value = job.get(key)
    if not isinstance(value, str) or not value:
        raise RenderError(f"job field {key} is missing")
    return Path(value)


def _validate_dimensions(size: tuple[int, int], label: str) -> tuple[int, int]:
    try:
        width, height = int(size[0]), int(size[1])
    except (IndexError, TypeError, ValueError) as error:
        raise RenderError(f"{label} dimensions are invalid") from error
    if width <= 0 or height <= 0:
        raise RenderError(f"{label} dimensions are invalid")
    if width > MAX_EDGE or height > MAX_EDGE:
        raise RenderError(f"{label} edge exceeds {MAX_EDGE} pixels")
    if width * height > MAX_PIXELS:
        raise RenderError(f"{label} exceeds {MAX_PIXELS} pixels")
    return width, height


def _pil_duration_ms(image: Any) -> int:
    value = image.info.get("duration", 100) or 100
    try:
        duration = int(value)
    except (TypeError, ValueError) as error:
        raise RenderError("source frame duration is invalid") from error
    if duration <= 0:
        raise RenderError("source frame duration is invalid")
    return duration


def _scan_pil_source(path: Path) -> _MediaInfo:
    from PIL import Image

    try:
        with Image.open(path) as image:
            frame_count = int(getattr(image, "n_frames", 1))
            if frame_count <= 0:
                raise RenderError("source has no frames")
            if frame_count > MAX_FRAMES:
                raise RenderError(f"source has more than {MAX_FRAMES} frames")
            source_size: tuple[int, int] | None = None
            duration_ms = 0
            for index in range(frame_count):
                image.seek(index)
                image.load()
                frame_size = _validate_dimensions(image.size, "source")
                if source_size is None:
                    source_size = frame_size
                elif source_size != frame_size:
                    raise RenderError("source frame dimensions differ")
                duration_ms += _pil_duration_ms(image)
                if duration_ms > MAX_DURATION_MS:
                    raise RenderError(
                        f"source duration exceeds {MAX_DURATION_MS // 1000} seconds"
                    )
    except RenderError:
        raise
    except Exception as error:
        raise RenderError("source image cannot be inspected") from error
    if source_size is None:
        raise RenderError("source has no frames")
    return _MediaInfo(
        source_size[0],
        source_size[1],
        frame_count,
        duration_ms,
        None,
        True,
    )


def _parse_fps(metadata: dict[str, Any]) -> float:
    value = metadata.get("fps")
    if value is None:
        value = metadata.get("framerate")
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            value = float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError) as error:
            raise RenderError("video frame rate is invalid") from error
    try:
        fps = float(value)
    except (TypeError, ValueError) as error:
        raise RenderError("video frame rate is missing") from error
    if not math.isfinite(fps) or fps <= 0:
        raise RenderError("video frame rate is invalid")
    return fps


def _video_reader(path: Path) -> Iterator[Any]:
    import imageio_ffmpeg

    return imageio_ffmpeg.read_frames(
        str(path),
        input_params=["-threads", "1"],
        output_params=["-threads", "1", "-filter_threads", "1"],
    )


def _close_reader(reader: Any) -> None:
    close = getattr(reader, "close", None)
    if callable(close):
        close()


def _array_size(frame_bytes: bytes, metadata: dict[str, Any]) -> tuple[int, int]:
    value = metadata.get("size") or metadata.get("source_size")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise RenderError("video dimensions are missing")
    size = _validate_dimensions((int(value[0]), int(value[1])), "source")
    if len(frame_bytes) != size[0] * size[1] * 3:
        raise RenderError("video frame dimensions are invalid")
    return size


def _scan_video_source(path: Path) -> _MediaInfo:
    reader = None
    try:
        reader = _video_reader(path)
        metadata = next(reader)
        if not isinstance(metadata, dict):
            raise RenderError("video metadata is invalid")
        fps = _parse_fps(metadata)
        frame_duration_ms = max(1, int(round(1000 / fps)))
        frame_count = 0
        source_size: tuple[int, int] | None = None
        for frame_bytes in reader:
            frame_size = _array_size(frame_bytes, metadata)
            if source_size is None:
                source_size = frame_size
            elif source_size != frame_size:
                raise RenderError("source frame dimensions differ")
            frame_count += 1
            if frame_count > MAX_FRAMES:
                raise RenderError(f"source has more than {MAX_FRAMES} frames")
            if frame_count * frame_duration_ms > MAX_DURATION_MS:
                raise RenderError(
                    f"source duration exceeds {MAX_DURATION_MS // 1000} seconds"
                )
    except StopIteration as error:
        raise RenderError("video metadata is missing") from error
    except RenderError:
        raise
    except Exception as error:
        raise RenderError("video cannot be inspected") from error
    finally:
        if reader is not None:
            _close_reader(reader)
    if source_size is None or frame_count == 0:
        raise RenderError("source has no frames")
    return _MediaInfo(
        source_size[0],
        source_size[1],
        frame_count,
        frame_count * frame_duration_ms,
        frame_duration_ms,
        False,
    )


def _scan_source(path: Path) -> _MediaInfo:
    if not path.is_file():
        raise RenderError("source media file is missing")
    if path.suffix.lower() in _PIL_EXTENSIONS:
        return _scan_pil_source(path)
    return _scan_video_source(path)


def _iter_pil_frames(path: Path, frame_count: int) -> Iterator[tuple[Any, int]]:
    from PIL import Image

    with Image.open(path) as image:
        if int(getattr(image, "n_frames", 1)) != frame_count:
            raise RenderError("source frame count changed")
        for index in range(frame_count):
            image.seek(index)
            image.load()
            duration_ms = _pil_duration_ms(image)
            frame = image.convert("RGBA")
            try:
                yield frame, duration_ms
            finally:
                frame.close()


def _iter_video_frames(
    path: Path,
    info: _MediaInfo,
) -> Iterator[tuple[Any, int]]:
    from PIL import Image

    reader = None
    try:
        reader = _video_reader(path)
        metadata = next(reader)
        for frame_bytes in reader:
            _array_size(frame_bytes, metadata)
            base = Image.frombytes("RGB", (info.width, info.height), frame_bytes)
            frame = base.convert("RGBA")
            base.close()
            try:
                yield frame, info.frame_duration_ms or 0
            finally:
                frame.close()
    finally:
        if reader is not None:
            _close_reader(reader)


def _iter_source_frames(
    path: Path,
    info: _MediaInfo,
) -> Iterator[tuple[Any, int]]:
    if info.pil_source:
        yield from _iter_pil_frames(path, info.frame_count)
    else:
        yield from _iter_video_frames(path, info)


def _load_avatar(path: Path) -> Any:
    if not path.is_file():
        raise RenderError("avatar file is missing")
    from PIL import Image

    try:
        with Image.open(path) as image:
            _validate_dimensions(image.size, "avatar")
            converted = image.convert("RGBA")
    except RenderError:
        raise
    except Exception as error:
        raise RenderError("avatar image cannot be read") from error
    try:
        # Avatar art rarely needs to be larger than the output. Resize once upfront.
        shrunk = _shrink_avatar(converted)
    except Exception as error:
        converted.close()
        raise RenderError("avatar image cannot be resized") from error
    if shrunk is not converted:
        converted.close()
    return shrunk


def _keyframes(annotation: dict[str, Any], side: str) -> list[dict[str, Any]]:
    value = annotation.get("keyframes", {})
    if value is None:
        return []
    if not isinstance(value, dict):
        raise RenderError("annotation keyframes are invalid")
    frames = value.get(side, [])
    if frames is None:
        return []
    if not isinstance(frames, list):
        raise RenderError("annotation keyframes are invalid")
    for frame in frames:
        if not isinstance(frame, dict):
            raise RenderError("annotation keyframes are invalid")
        for field in ("t", "x", "y", "w", "h"):
            number = frame.get(field)
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise RenderError("annotation keyframes are invalid")
            if not math.isfinite(float(number)):
                raise RenderError("annotation keyframes are invalid")
        angle = frame.get("angle", 0)
        if isinstance(angle, bool) or not isinstance(angle, (int, float)):
            raise RenderError("annotation keyframes are invalid")
        if not math.isfinite(float(angle)):
            raise RenderError("annotation keyframes are invalid")
    return frames


def _output_size(width: int, height: int) -> tuple[int, int]:
    # libx264 needs even dimensions
    scale = min(1.0, MAX_OUTPUT_DIM / max(width, height))
    output_width = max(2, int(width * scale))
    output_height = max(2, int(height * scale))
    output_width -= output_width % 2
    output_height -= output_height % 2
    return max(2, output_width), max(2, output_height)


def _scale_box(box: dict[str, float], scale_x: float, scale_y: float) -> dict[str, float]:
    scaled = dict(box)
    scaled["x"] = box["x"] * scale_x
    scaled["y"] = box["y"] * scale_y
    scaled["w"] = box["w"] * scale_x
    scaled["h"] = box["h"] * scale_y
    return scaled


def _write_frame(
    stdin: Any,
    source_frame: Any,
    cumulative_ms: int,
    output_size: tuple[int, int],
    source_size: tuple[int, int],
    keyframes_a: list[dict[str, Any]],
    keyframes_b: list[dict[str, Any]],
    avatar_a: Any,
    avatar_b: Any,
) -> None:
    from PIL import Image

    frame = source_frame
    resized = source_frame.size != output_size
    if resized:
        frame = source_frame.resize(output_size, Image.LANCZOS)
    try:
        scale_x = output_size[0] / source_size[0]
        scale_y = output_size[1] / source_size[1]
        t = cumulative_ms / 1000.0
        for keyframes, avatar in ((keyframes_a, avatar_a), (keyframes_b, avatar_b)):
            box = _interpolate(keyframes, t)
            if box is not None:
                _draw_avatar_circumscribed(
                    frame,
                    avatar,
                    _scale_box(box, scale_x, scale_y),
                )
        background = Image.new("RGB", output_size, (255, 255, 255))
        try:
            mask = frame.getchannel("A")
            try:
                background.paste(frame, mask=mask)
            finally:
                mask.close()
            stdin.write(background.tobytes())
        finally:
            background.close()
    except BrokenPipeError as error:
        raise RenderError("ffmpeg stopped while encoding") from error
    except RenderError:
        raise
    except Exception as error:
        raise RenderError("frame compositing failed") from error
    finally:
        if resized:
            frame.close()


def _ffmpeg_error(stderr: bytes) -> RenderError:
    message = stderr.decode(errors="replace").strip() or "unknown error"
    return RenderError(f"ffmpeg failed: {message[-500:]}")


def _encode(
    source_path: Path,
    info: _MediaInfo,
    output_path: Path,
    keyframes_a: list[dict[str, Any]],
    keyframes_b: list[dict[str, Any]],
    avatar_a: Any,
    avatar_b: Any,
) -> None:
    output_size = _output_size(info.width, info.height)
    # Exact fraction preserves the original timing without rounding drift.
    fps = f"{info.frame_count * 1000}/{info.duration_ms}"
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-filter_threads", "1",
        "-threads", "1", "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{output_size[0]}x{output_size[1]}",
        "-framerate", fps, "-i", "-", "-an", "-c:v", "libx264", "-threads", "1",
        "-pix_fmt", "yuv420p", "-crf", "26", "-preset", "veryfast",
        "-movflags", "+faststart", str(output_path),
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise RenderError("ffmpeg is unavailable") from error

    completed = False
    try:
        if process.stdin is None:
            raise RenderError("ffmpeg input is unavailable")
        frame_count = 0
        cumulative_ms = 0
        source_frames = _iter_source_frames(source_path, info)
        try:
            for source_frame, duration_ms in source_frames:
                if source_frame.size != (info.width, info.height):
                    raise RenderError("source frame dimensions changed")
                _write_frame(
                    process.stdin,
                    source_frame,
                    cumulative_ms,
                    output_size,
                    (info.width, info.height),
                    keyframes_a,
                    keyframes_b,
                    avatar_a,
                    avatar_b,
                )
                frame_count += 1
                cumulative_ms += duration_ms
        finally:
            source_frames.close()
        if frame_count != info.frame_count or cumulative_ms != info.duration_ms:
            raise RenderError("source changed while rendering")
        process.stdin.close()
        process.stdin = None
        _stdout, stderr = process.communicate()
        if process.returncode != 0:
            raise _ffmpeg_error(stderr or b"")
        completed = True
    except RenderError:
        raise
    except BrokenPipeError as error:
        raise RenderError("ffmpeg stopped while encoding") from error
    except Exception as error:
        raise RenderError("rendering failed") from error
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except Exception:
                pass
        if not completed and process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        if not completed:
            try:
                process.wait()
            except Exception:
                pass
        if process.stderr is not None:
            process.stderr.close()
        if not completed:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass


def render_job(job: dict[str, Any]) -> dict[str, int]:
    if not isinstance(job, dict):
        raise RenderError("job must be an object")
    annotation = job.get("annotation")
    if not isinstance(annotation, dict):
        raise RenderError("job annotation is missing")
    source_path = _path_from_job(job, "source_path")
    avatar_a_path = _path_from_job(job, "avatar_a_path")
    avatar_b_path = _path_from_job(job, "avatar_b_path")
    output_path = _path_from_job(job, "output_path")
    info = _scan_source(source_path)
    keyframes_a = _keyframes(annotation, "a")
    keyframes_b = _keyframes(annotation, "b")
    avatar_a = _load_avatar(avatar_a_path)
    avatar_b = None
    try:
        avatar_b = _load_avatar(avatar_b_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _encode(
            source_path,
            info,
            output_path,
            keyframes_a,
            keyframes_b,
            avatar_a,
            avatar_b,
        )
    finally:
        avatar_a.close()
        if avatar_b is not None:
            avatar_b.close()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    peak_rss_kib = int(usage.ru_maxrss)
    child_peak_rss_kib = int(child_usage.ru_maxrss)
    if sys.platform == "darwin":
        peak_rss_kib //= 1024
        child_peak_rss_kib //= 1024
    width, height = _output_size(info.width, info.height)
    return {
        "width": width,
        "height": height,
        "frames": info.frame_count,
        "duration_ms": info.duration_ms,
        "peak_rss_kib": peak_rss_kib,
        "child_peak_rss_kib": child_peak_rss_kib,
    }


def _stop_worker(_signum: int, _frame: Any) -> None:
    raise RenderError("worker stopped")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        _set_address_space_limit()
        signal.signal(signal.SIGTERM, _stop_worker)
        if len(args) != 1:
            raise RenderError("usage: python -m steward.helpers.fuck_renderer <job.json>")
        try:
            job = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        except Exception as error:
            raise RenderError("job JSON cannot be read") from error
        summary = render_job(job)
    except RenderError as error:
        print(f"fuck_renderer: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("fuck_renderer: rendering failed", file=sys.stderr)
        return 1
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
