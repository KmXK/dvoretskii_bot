from __future__ import annotations

import bisect
import json
import math
import os
import resource
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


OUTPUT_FPS = 25
MAX_OUTPUT_DIM = 480
MAX_PIXELS = 4_000_000
MAX_DURATION_SECONDS = 20.0
MAX_TEMPLATE_DURATION_SECONDS = 30.0
MAX_SOURCE_BYTES = 30 * 1024 * 1024
MAX_INSERT_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_IMAGE_FRAMES = 5000
MAX_KEYFRAMES = 1024
MAX_EDGE = 4096
MAX_OVERLAY_DIAMETER = 2048
PROBE_TIMEOUT_SECONDS = 10
PROCESS_TIMEOUT_SECONDS = 50
STDERR_LIMIT = 64 * 1024
DATA_MEMORY_LIMIT_BYTES = 512 * 1024**2
ADDRESS_SPACE_LIMIT_BYTES = 2 * 1024**3

_IMAGE_SIGNATURES = (b"GIF87a", b"GIF89a", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")


class RenderError(ValueError, RuntimeError):
    pass


@dataclass(frozen=True)
class _MediaInfo:
    kind: str
    width: int
    height: int
    duration_seconds: float
    durations_ms: tuple[int, ...] = ()


class _Deadline:
    def __init__(self, seconds: float) -> None:
        self.value = time.monotonic() + seconds

    def remaining(self) -> float:
        return self.value - time.monotonic()


class _PipeCapture:
    def __init__(self, stream: Any, limit: int) -> None:
        self.stream = stream
        self.limit = limit
        self.data = bytearray()
        self.thread = threading.Thread(target=self._read, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _read(self) -> None:
        while True:
            chunk = self.stream.read(8192)
            if not chunk:
                return
            if len(self.data) < self.limit:
                self.data.extend(chunk[: self.limit - len(self.data)])

    def join(self) -> None:
        self.thread.join(timeout=1)


def _terminate_process(process: Any) -> None:
    try:
        process.kill()
    except (ProcessLookupError, OSError):
        pass


def _wait_process(process: Any, deadline: _Deadline, stderr: _PipeCapture | None) -> int:
    try:
        return process.wait(timeout=max(0.01, deadline.remaining()))
    except subprocess.TimeoutExpired as error:
        _terminate_process(process)
        try:
            process.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass
        if stderr is not None:
            stderr.join()
        raise RenderError("внешний процесс превысил лимит времени") from error
    finally:
        if stderr is not None:
            stderr.join()


def _run_capture(command: list[str], deadline: _Deadline) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except OSError as error:
        raise RenderError("не удалось запустить внешний процесс") from error
    stdout_capture = _PipeCapture(process.stdout, 1024 * 1024)
    stderr_capture = _PipeCapture(process.stderr, STDERR_LIMIT)
    stdout_capture.start()
    stderr_capture.start()
    try:
        returncode = _wait_process(process, deadline, stderr_capture)
    except Exception:
        _terminate_process(process)
        try:
            process.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass
        stdout_capture.join()
        raise
    stdout_capture.join()
    return returncode, bytes(stdout_capture.data), bytes(stderr_capture.data)


def _file_size(path: Path, limit: int, label: str) -> int:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise RenderError(f"{label}: файл недоступен") from error
    if not path.is_file() or size <= 0:
        raise RenderError(f"{label}: файл недоступен")
    if size > limit:
        raise RenderError(f"{label}: файл больше {limit // (1024 * 1024)} МБ")
    return size


def _validate_dimensions(size: tuple[Any, Any], label: str) -> tuple[int, int]:
    try:
        width_value, height_value = size
        width = int(width_value)
        height = int(height_value)
    except (TypeError, ValueError) as error:
        raise RenderError(f"{label}: некорректные размеры") from error
    if (
        isinstance(width_value, bool)
        or isinstance(height_value, bool)
        or width != width_value
        or height != height_value
        or width <= 0
        or height <= 0
    ):
        raise RenderError(f"{label}: некорректные размеры")
    if width > MAX_EDGE or height > MAX_EDGE:
        raise RenderError(f"{label}: сторона больше {MAX_EDGE} пикселей")
    if width * height > MAX_PIXELS:
        raise RenderError(f"{label}: больше {MAX_PIXELS} пикселей")
    return width, height


def _duration_ms(image: Any, label: str) -> int:
    value = image.info.get("duration")
    if value is None or value == 0:
        return 100
    if isinstance(value, bool):
        raise RenderError(f"{label}: некорректная длительность кадра")
    try:
        duration = float(value)
    except (TypeError, ValueError) as error:
        raise RenderError(f"{label}: некорректная длительность кадра") from error
    if not math.isfinite(duration) or duration <= 0:
        raise RenderError(f"{label}: некорректная длительность кадра")
    return max(1, int(round(duration)))


def _scan_pil(path: Path, label: str, max_duration_seconds: float) -> _MediaInfo:
    from PIL import Image

    try:
        with Image.open(path) as image:
            frame_count = int(getattr(image, "n_frames", 1))
            if frame_count <= 0:
                raise RenderError(f"{label}: нет кадров")
            if frame_count > MAX_IMAGE_FRAMES:
                raise RenderError(f"{label}: слишком много кадров")
            source_size = _validate_dimensions(image.size, label)
            image_format = image.format
            durations: list[int] = []
            total_ms = 0
            for index in range(frame_count):
                image.seek(index)
                image.load()
                frame_size = _validate_dimensions(image.size, label)
                if frame_size != source_size:
                    raise RenderError(f"{label}: размеры кадров различаются")
                frame_duration = _duration_ms(image, label)
                durations.append(frame_duration)
                total_ms += frame_duration
                if total_ms > max_duration_seconds * 1000:
                    raise RenderError(f"{label}: длительность больше {int(max_duration_seconds)} секунд")
    except RenderError:
        raise
    except Exception as error:
        raise RenderError(f"{label}: изображение не удалось прочитать") from error
    if frame_count == 1 and image_format not in {"GIF", "WEBP"}:
        durations = [1000]
        total_ms = 1000
    return _MediaInfo(
        kind="pil",
        width=source_size[0],
        height=source_size[1],
        duration_seconds=total_ms / 1000,
        durations_ms=tuple(durations),
    )


def _parse_rate(value: Any, label: str) -> float:
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            value = float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError) as error:
            raise RenderError(f"{label}: некорректный fps") from error
    try:
        rate = float(value)
    except (TypeError, ValueError) as error:
        raise RenderError(f"{label}: некорректный fps") from error
    if not math.isfinite(rate) or rate <= 0:
        raise RenderError(f"{label}: некорректный fps")
    return rate


def _parse_positive(value: Any, label: str) -> float | None:
    if value is None or value == "N/A":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise RenderError(f"{label}: некорректное число") from error
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _probe_video(
    path: Path,
    label: str,
    deadline: _Deadline,
    max_duration_seconds: float,
) -> _MediaInfo:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,duration,nb_frames:stream_side_data=rotation:format=duration",
        "-of",
        "json",
        str(path),
    ]
    probe_deadline = _Deadline(min(PROBE_TIMEOUT_SECONDS, max(0.01, deadline.remaining())))
    returncode, stdout, stderr = _run_capture(command, probe_deadline)
    if returncode != 0:
        message = stderr.decode(errors="replace").strip()
        suffix = f": {message[-300:]}" if message else ""
        raise RenderError(f"{label}: видео не удалось прочитать{suffix}")
    try:
        payload = json.loads(stdout)
        stream = payload["streams"][0]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise RenderError(f"{label}: ffprobe вернул некорректные данные") from error
    width, height = _validate_dimensions((stream.get("width"), stream.get("height")), label)
    for side_data in stream.get("side_data_list", []):
        rotation = side_data.get("rotation")
        if rotation is not None and int(round(float(rotation) / 90)) % 2:
            width, height = height, width
            break

    fps_value = stream.get("r_frame_rate") or stream.get("avg_frame_rate")
    fps = _parse_rate(fps_value, label)
    duration = _parse_positive(stream.get("duration"), label)
    if duration is None:
        duration = _parse_positive(payload.get("format", {}).get("duration"), label)
    if duration is None:
        frames = _parse_positive(stream.get("nb_frames"), label)
        if frames is not None:
            duration = frames / fps
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise RenderError(f"{label}: длительность видео неизвестна")
    if duration > max_duration_seconds + 1e-6:
        raise RenderError(f"{label}: длительность больше {int(max_duration_seconds)} секунд")
    return _MediaInfo(
        kind="video",
        width=width,
        height=height,
        duration_seconds=duration,
    )


def _looks_like_image(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(16)
    except OSError:
        return False
    if header.startswith(_IMAGE_SIGNATURES):
        return True
    return header[:4] == b"RIFF" and header[8:12] == b"WEBP"


def _scan_media(
    path: Path,
    label: str,
    limit: int,
    deadline: _Deadline,
    max_duration_seconds: float,
) -> _MediaInfo:
    _file_size(path, limit, label)
    try:
        return _scan_pil(path, label, max_duration_seconds)
    except RenderError:
        if _looks_like_image(path):
            raise
    return _probe_video(path, label, deadline, max_duration_seconds)


def _output_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, MAX_OUTPUT_DIM / max(width, height))
    output_width = max(2, int(math.floor(width * scale)))
    output_height = max(2, int(math.floor(height * scale)))
    if output_width % 2:
        output_width -= 1
    if output_height % 2:
        output_height -= 1
    return max(2, output_width), max(2, output_height)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RenderError(f"annotation: {label} должен быть числом")
    number = float(value)
    if not math.isfinite(number):
        raise RenderError(f"annotation: {label} должен быть конечным")
    return number


def _prepare_keyframes(
    annotation: dict[str, Any],
    source_size: tuple[int, int],
    output_size: tuple[int, int],
    duration_seconds: float,
) -> dict[str, list[dict[str, Any]]]:
    raw_keyframes = annotation.get("keyframes", {})
    if raw_keyframes is None:
        raw_keyframes = {}
    if not isinstance(raw_keyframes, dict):
        raise RenderError("annotation: keyframes должен быть объектом")
    source_width, source_height = source_size
    scale_x = output_size[0] / source_width
    scale_y = output_size[1] / source_height
    coordinate_limit = max(source_width, source_height) * 4
    size_limit = max(source_width, source_height) * 2
    prepared: dict[str, list[dict[str, Any]]] = {}
    for side in ("a", "b"):
        raw_frames = raw_keyframes.get(side, [])
        if raw_frames is None:
            raw_frames = []
        if not isinstance(raw_frames, list):
            raise RenderError(f"annotation: keyframes[{side}] должен быть списком")
        if len(raw_frames) > MAX_KEYFRAMES:
            raise RenderError(f"annotation: слишком много keyframes[{side}]")
        frames: list[dict[str, Any]] = []
        previous_t = -math.inf
        for index, raw_frame in enumerate(raw_frames):
            if not isinstance(raw_frame, dict):
                raise RenderError(f"annotation: keyframes[{side}][{index}] должен быть объектом")
            t = _number(raw_frame.get("t"), f"keyframes[{side}][{index}].t")
            x = _number(raw_frame.get("x"), f"keyframes[{side}][{index}].x")
            y = _number(raw_frame.get("y"), f"keyframes[{side}][{index}].y")
            width = _number(raw_frame.get("w"), f"keyframes[{side}][{index}].w")
            height = _number(raw_frame.get("h"), f"keyframes[{side}][{index}].h")
            angle = _number(raw_frame.get("angle", 0), f"keyframes[{side}][{index}].angle")
            if t < 0 or t > duration_seconds + 1e-6:
                raise RenderError(f"annotation: время keyframes[{side}][{index}] вне ролика")
            if t < previous_t:
                raise RenderError(f"annotation: keyframes[{side}] не отсортированы по времени")
            if width <= 0 or height <= 0:
                raise RenderError(f"annotation: размеры keyframes[{side}][{index}] должны быть положительными")
            if width > size_limit or height > size_limit:
                raise RenderError(f"annotation: слишком большой bbox keyframes[{side}][{index}]")
            if abs(x) > coordinate_limit or abs(y) > coordinate_limit:
                raise RenderError(f"annotation: bbox keyframes[{side}][{index}] выходит за допустимые координаты")
            if abs(x) + width > coordinate_limit * 2 or abs(y) + height > coordinate_limit * 2:
                raise RenderError(f"annotation: bbox keyframes[{side}][{index}] выходит за допустимые границы")
            if abs(angle) > 36000:
                raise RenderError(f"annotation: угол keyframes[{side}][{index}] слишком большой")
            visible = raw_frame.get("visible", True)
            if not isinstance(visible, bool):
                raise RenderError(f"annotation: visible keyframes[{side}][{index}] должен быть bool")
            frames.append({
                "t": t,
                "x": x * scale_x,
                "y": y * scale_y,
                "w": width * scale_x,
                "h": height * scale_y,
                "angle": angle,
                "visible": visible,
            })
            previous_t = t
        prepared[side] = frames
    return prepared


def _lerp(first: float, second: float, ratio: float) -> float:
    return first + (second - first) * ratio


def _interpolate(keyframes: list[dict[str, Any]], seconds: float) -> dict[str, float] | None:
    if not keyframes:
        return None
    if seconds <= keyframes[0]["t"]:
        current = keyframes[0]
        return None if not current["visible"] else dict(current)
    if seconds >= keyframes[-1]["t"]:
        current = keyframes[-1]
        return None if not current["visible"] else dict(current)
    for first, second in zip(keyframes, keyframes[1:]):
        if first["t"] <= seconds <= second["t"]:
            if not first["visible"]:
                return None
            span = second["t"] - first["t"]
            ratio = (seconds - first["t"]) / span if span > 0 else 0.0
            return {
                "x": _lerp(first["x"], second["x"], ratio),
                "y": _lerp(first["y"], second["y"], ratio),
                "w": _lerp(first["w"], second["w"], ratio),
                "h": _lerp(first["h"], second["h"], ratio),
                "angle": _lerp(first["angle"], second["angle"], ratio),
            }
    return None


class _PilReader:
    def __init__(self, path: Path, info: _MediaInfo) -> None:
        from PIL import Image

        self.path = path
        self.info = info
        self.image = Image.open(path)
        self.starts_ms: list[int] = []
        current_ms = 0
        for duration in info.durations_ms:
            self.starts_ms.append(current_ms)
            current_ms += duration
        self.current_index = -1
        self.current_frame: Any = None

    def _reset(self) -> None:
        from PIL import Image

        if self.current_frame is not None:
            self.current_frame.close()
            self.current_frame = None
        self.image.close()
        self.image = Image.open(self.path)
        self.current_index = -1

    def _load_index(self, index: int) -> Any:
        if index < self.current_index:
            self._reset()
        self.image.seek(index)
        self.image.load()
        frame = self.image.convert("RGBA")
        if self.current_frame is not None:
            self.current_frame.close()
        self.current_frame = frame
        self.current_index = index
        return frame

    def frame_at(self, seconds: float, loop: bool) -> Any:
        duration_ms = sum(self.info.durations_ms)
        position_ms = seconds * 1000
        if loop:
            position_ms %= duration_ms
        else:
            position_ms = min(max(0.0, position_ms), max(0.0, duration_ms - 0.001))
        index = bisect.bisect_right(self.starts_ms, position_ms) - 1
        index = max(0, min(index, len(self.starts_ms) - 1))
        return self._load_index(index)

    def close(self) -> None:
        if self.current_frame is not None:
            self.current_frame.close()
            self.current_frame = None
        self.image.close()


def _read_exact(stream: Any, size: int, deadline: _Deadline) -> bytes:
    fd = stream.fileno()
    result = bytearray()
    while len(result) < size:
        remaining = deadline.remaining()
        if remaining <= 0:
            raise RenderError("декодер превысил лимит времени")
        readable, _, _ = select.select([fd], [], [], min(remaining, 0.5))
        if not readable:
            continue
        chunk = os.read(fd, size - len(result))
        if not chunk:
            break
        result.extend(chunk)
    return bytes(result)


class _VideoReader:
    def __init__(self, path: Path, info: _MediaInfo, deadline: _Deadline, loop: bool) -> None:
        self.path = path
        self.info = info
        self.deadline = deadline
        self.loop = loop
        self.process: Any = None
        self.stderr: _PipeCapture | None = None
        self._start()

    def _start(self) -> None:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-filter_complex_threads",
            "1",
        ]
        if self.loop:
            command.extend(["-stream_loop", "-1"])
        command.extend([
            "-i",
            str(self.path),
            "-map",
            "0:v:0",
            "-vf",
            f"fps={OUTPUT_FPS}",
            "-an",
            "-sn",
            "-dn",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-threads",
            "1",
        ])
        if not self.loop:
            command.extend([
                "-frames:v",
                str(_target_frames(self.info.duration_seconds, MAX_TEMPLATE_DURATION_SECONDS)),
            ])
        command.append("-")
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as error:
            raise RenderError("не удалось запустить ffmpeg для декодирования") from error
        self.stderr = _PipeCapture(self.process.stderr, STDERR_LIMIT)
        self.stderr.start()

    def next_frame(self) -> Any:
        from PIL import Image

        frame_size = self.info.width * self.info.height * 3
        data = _read_exact(self.process.stdout, frame_size, self.deadline)
        if len(data) != frame_size:
            message = bytes(self.stderr.data if self.stderr is not None else b"").decode(errors="replace")
            suffix = f": {message[-300:]}" if message else ""
            raise RenderError(f"видео закончилось раньше ожидаемого кадра{suffix}")
        return Image.frombytes("RGB", (self.info.width, self.info.height), data).convert("RGBA")

    def close(self) -> None:
        if self.process is None:
            return
        try:
            self.process.stdout.close()
        except (AttributeError, OSError):
            pass
        if self.process.poll() is None:
            _terminate_process(self.process)
        try:
            self.process.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass
        if self.stderr is not None:
            self.stderr.join()
        self.process = None


class _MediaReader:
    def __init__(self, path: Path, info: _MediaInfo, deadline: _Deadline, loop: bool) -> None:
        self.info = info
        self.pil: _PilReader | None = None
        self.video: _VideoReader | None = None
        if info.kind == "pil":
            self.pil = _PilReader(path, info)
        else:
            self.video = _VideoReader(path, info, deadline, loop)

    def template_frame(self, seconds: float) -> Any:
        if self.pil is not None:
            return self.pil.frame_at(seconds, loop=False)
        return self.video.next_frame()

    def avatar_frame(self, seconds: float) -> Any:
        if self.pil is not None:
            return self.pil.frame_at(seconds, loop=True)
        return self.video.next_frame()

    def close(self) -> None:
        if self.pil is not None:
            self.pil.close()
        if self.video is not None:
            self.video.close()


def _load_static_avatar(path: Path) -> Any:
    from PIL import Image

    _file_size(path, MAX_INSERT_BYTES, "avatar A")
    try:
        with Image.open(path) as image:
            _validate_dimensions(image.size, "avatar A")
            image.seek(0)
            image.load()
            avatar = image.convert("RGBA")
    except RenderError:
        raise
    except Exception as error:
        raise RenderError("avatar A: ожидается изображение") from error
    if max(avatar.size) > MAX_OVERLAY_DIAMETER:
        scale = MAX_OVERLAY_DIAMETER / max(avatar.size)
        resized = avatar.resize(
            (max(1, int(round(avatar.width * scale))), max(1, int(round(avatar.height * scale)))),
            Image.Resampling.LANCZOS,
        )
        avatar.close()
        avatar = resized
    return avatar


def _draw_avatar(frame: Any, avatar: Any, box: dict[str, float]) -> None:
    from PIL import Image, ImageChops, ImageDraw, ImageOps

    width = float(box["w"])
    height = float(box["h"])
    diameter = int(math.ceil(math.hypot(width, height)))
    if diameter < 2 or diameter > MAX_OVERLAY_DIAMETER:
        raise RenderError("annotation: размер overlay слишком большой")
    converted = avatar.convert("RGBA")
    fitted = ImageOps.fit(
        converted,
        (diameter, diameter),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    converted.close()
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    with fitted.getchannel("A") as original_alpha:
        with ImageChops.multiply(original_alpha, mask) as combined_alpha:
            fitted.putalpha(combined_alpha)
    angle = float(box.get("angle", 0)) % 360
    if angle:
        # Annotator/canvas convention: positive angle = clockwise.
        # PIL.rotate is CCW, so negate.
        rotated = fitted.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
        fitted.close()
        fitted = rotated
    center_x = float(box["x"]) + width / 2
    center_y = float(box["y"]) + height / 2
    position = (
        int(round(center_x - fitted.width / 2)),
        int(round(center_y - fitted.height / 2)),
    )
    try:
        frame.alpha_composite(fitted, position)
    finally:
        mask.close()
        fitted.close()


def _target_frames(
    duration_seconds: float,
    max_duration_seconds: float = MAX_DURATION_SECONDS,
) -> int:
    frames = max(1, int(math.ceil(duration_seconds * OUTPUT_FPS - 1e-9)))
    return min(frames, int(max_duration_seconds * OUTPUT_FPS))


def _write_pipe(stream: Any, data: bytes, deadline: _Deadline) -> None:
    fd = stream.fileno()
    position = 0
    while position < len(data):
        remaining = deadline.remaining()
        if remaining <= 0:
            raise RenderError("кодировщик превысил лимит времени")
        _, writable, _ = select.select([], [fd], [], min(remaining, 0.5))
        if not writable:
            continue
        try:
            written = os.write(fd, data[position:])
        except BrokenPipeError as error:
            raise RenderError("ffmpeg остановился во время кодирования") from error
        if written <= 0:
            raise RenderError("ffmpeg не принимает кадры")
        position += written


def _encode(
    output_path: Path,
    output_size: tuple[int, int],
    frame_count: int,
    source_reader: _MediaReader,
    avatar_a: Any,
    avatar_b_reader: _MediaReader,
    keyframes: dict[str, list[dict[str, Any]]],
    deadline: _Deadline,
) -> None:
    from PIL import Image

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{output_size[0]}x{output_size[1]}",
        "-framerate",
        str(OUTPUT_FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-threads",
        "2",
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-frames:v",
        str(frame_count),
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except OSError as error:
        raise RenderError("не удалось запустить ffmpeg для кодирования") from error
    stderr_capture = _PipeCapture(process.stderr, STDERR_LIMIT)
    stderr_capture.start()
    completed = False
    try:
        for frame_index in range(frame_count):
            seconds = frame_index / OUTPUT_FPS
            source_frame = source_reader.template_frame(seconds)
            b_frame = avatar_b_reader.avatar_frame(seconds) if keyframes["b"] else None
            frame = source_frame.resize(output_size, Image.Resampling.LANCZOS)
            source_frame.close()
            try:
                for side, avatar in (("a", avatar_a), ("b", b_frame)):
                    box = _interpolate(keyframes[side], seconds)
                    if box is not None:
                        _draw_avatar(frame, avatar, box)
                rgb = Image.new("RGB", output_size, (255, 255, 255))
                try:
                    alpha = frame.getchannel("A")
                    try:
                        rgb.paste(frame, mask=alpha)
                    finally:
                        alpha.close()
                    _write_pipe(process.stdin, rgb.tobytes(), deadline)
                finally:
                    rgb.close()
            finally:
                frame.close()
            if b_frame is not None and avatar_b_reader.info.kind == "video":
                b_frame.close()
        process.stdin.close()
        process.stdin = None
        _wait_process(process, deadline, stderr_capture)
        if process.returncode != 0:
            message = bytes(stderr_capture.data).decode(errors="replace").strip()
            suffix = f": {message[-500:]}" if message else ""
            raise RenderError(f"ffmpeg: кодировщик завершился с ошибкой{suffix}")
        completed = True
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if not completed and process.poll() is None:
            _terminate_process(process)
        if not completed:
            try:
                process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                pass
        stderr_capture.join()
    try:
        size = output_path.stat().st_size
    except OSError as error:
        raise RenderError("ffmpeg не создал результат") from error
    if size <= 0:
        raise RenderError("ffmpeg создал пустой результат")
    if size > MAX_OUTPUT_BYTES:
        raise RenderError(f"результат больше {MAX_OUTPUT_BYTES // (1024 * 1024)} МБ")


def compose_mp4(
    source_path: Path,
    annotation: dict,
    avatar_a_path: Path,
    avatar_b_path: Path,
    output_path: Path,
) -> None:
    if not isinstance(annotation, dict):
        raise RenderError("annotation должен быть объектом")
    deadline = _Deadline(PROCESS_TIMEOUT_SECONDS)
    source_info = _scan_media(
        source_path,
        "шаблон",
        MAX_SOURCE_BYTES,
        deadline,
        MAX_TEMPLATE_DURATION_SECONDS,
    )
    output_size = _output_size(source_info.width, source_info.height)
    keyframes = _prepare_keyframes(
        annotation,
        (source_info.width, source_info.height),
        output_size,
        source_info.duration_seconds,
    )
    avatar_a = _load_static_avatar(avatar_a_path)
    avatar_b_info = _scan_media(
        avatar_b_path,
        "avatar B",
        MAX_INSERT_BYTES,
        deadline,
        MAX_DURATION_SECONDS,
    )
    source_reader = None
    avatar_b_reader = None
    temporary_path: Path | None = None
    try:
        source_reader = _MediaReader(source_path, source_info, deadline, loop=False)
        avatar_b_reader = _MediaReader(avatar_b_path, avatar_b_info, deadline, loop=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.name}.",
            suffix=".mp4",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        _encode(
            temporary_path,
            output_size,
            _target_frames(source_info.duration_seconds, MAX_TEMPLATE_DURATION_SECONDS),
            source_reader,
            avatar_a,
            avatar_b_reader,
            keyframes,
            deadline,
        )
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if source_reader is not None:
            source_reader.close()
        if avatar_b_reader is not None:
            avatar_b_reader.close()
        avatar_a.close()
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _set_memory_limits() -> None:
    try:
        resource.setrlimit(
            resource.RLIMIT_DATA,
            (DATA_MEMORY_LIMIT_BYTES, DATA_MEMORY_LIMIT_BYTES),
        )
        resource.setrlimit(
            resource.RLIMIT_AS,
            (ADDRESS_SPACE_LIMIT_BYTES, ADDRESS_SPACE_LIMIT_BYTES),
        )
    except (OSError, ValueError) as error:
        raise RenderError("не удалось установить лимит памяти worker") from error


def _path_from_job(job: dict[str, Any], key: str) -> Path:
    value = job.get(key)
    if not isinstance(value, str) or not value:
        raise RenderError(f"job: отсутствует {key}")
    return Path(value)


def render_job(job: dict[str, Any]) -> dict[str, int]:
    if not isinstance(job, dict):
        raise RenderError("job должен быть объектом")
    annotation = job.get("annotation", {})
    source_path = _path_from_job(job, "source_path")
    avatar_a_path = _path_from_job(job, "avatar_a_path")
    avatar_b_path = _path_from_job(job, "avatar_b_path")
    output_path = _path_from_job(job, "output_path")
    deadline = _Deadline(PROCESS_TIMEOUT_SECONDS)
    source_info = _scan_media(
        source_path,
        "шаблон",
        MAX_SOURCE_BYTES,
        deadline,
        MAX_TEMPLATE_DURATION_SECONDS,
    )
    compose_mp4(source_path, annotation, avatar_a_path, avatar_b_path, output_path)
    width, height = _output_size(source_info.width, source_info.height)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_rss_kib = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        peak_rss_kib //= 1024
    return {
        "width": width,
        "height": height,
        "frames": _target_frames(source_info.duration_seconds, MAX_TEMPLATE_DURATION_SECONDS),
        "duration_ms": int(round(source_info.duration_seconds * 1000)),
        "peak_rss_kib": peak_rss_kib,
    }


def _stop_worker(_signum: int, _frame: Any) -> None:
    raise RenderError("worker остановлен")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        _set_memory_limits()
        signal.signal(signal.SIGTERM, _stop_worker)
        if len(args) != 1:
            raise RenderError("использование: python -m steward.helpers.fuck_renderer <job.json>")
        try:
            job = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        except Exception as error:
            raise RenderError("job JSON не удалось прочитать") from error
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
