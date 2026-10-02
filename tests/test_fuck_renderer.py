import json
import math
import shutil
import subprocess
import sys

import pytest
from PIL import Image

from steward.helpers.fuck_renderer import RenderError, compose_mp4
from steward.helpers.fuck_render_job import run_render_job


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)


def _probe(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,nb_frames,duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout)["streams"][0]


def _raw_frames(path, size):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    frame_bytes = size[0] * size[1] * 3
    return [
        Image.frombytes("RGB", size, result.stdout[index:index + frame_bytes])
        for index in range(0, len(result.stdout), frame_bytes)
    ]


def _save_gif(path, colors, durations, size=(96, 64)):
    frames = [Image.new("RGBA", size, color) for color in colors]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
    )


def _save_color_video(path):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=48x48:r=1:d=5",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=48x48:r=1:d=5",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=48x48:r=1:d=10",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=48x48:r=1:d=3",
            "-filter_complex",
            "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0,format=yuv420p",
            "-r",
            "1",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )


@pytest.mark.parametrize("extension", ["gif", "mp4"])
def test_compose_truncates_long_animated_avatar(tmp_path, extension):
    source = tmp_path / "source.gif"
    _save_gif(
        source,
        ["white", "#fefefe", "#fdfdfd", "#fcfcfc"],
        [5000, 5000, 5000, 7000],
        size=(64, 64),
    )
    avatar_b = tmp_path / f"avatar-b.{extension}"
    if extension == "gif":
        _save_gif(
            avatar_b,
            ["red", "blue", "red", "green"],
            [5000, 5000, 10000, 3000],
            size=(48, 48),
        )
    else:
        _save_color_video(avatar_b)
    avatar_a = tmp_path / "avatar-a.png"
    Image.new("RGBA", (8, 8), "white").save(avatar_a)
    output = tmp_path / "output.mp4"

    compose_mp4(
        source,
        {"keyframes": {"b": [{"t": 0, "x": 16, "y": 16, "w": 32, "h": 32}]}},
        avatar_a,
        avatar_b,
        output,
    )

    info = _probe(output)
    assert float(info["duration"]) == pytest.approx(22, abs=0.08)
    frames = _raw_frames(output, (64, 64))
    assert len(frames) == 550
    sampled = [frames[index].getpixel((32, 32)) for index in (105, 130, 255, 505)]
    assert sampled[0][0] > sampled[0][2] + 80
    assert sampled[1][2] > sampled[1][0] + 80
    assert sampled[2][0] > sampled[2][2] + 80
    assert sampled[3][0] > sampled[3][2] + 80
    assert all(
        pixel[1] < pixel[0] + 40 and pixel[1] < pixel[2] + 40
        for pixel in (frame.getpixel((32, 32)) for frame in frames)
    )


def test_compose_keeps_delays_and_loops_animated_avatar(tmp_path):
    source = tmp_path / "source.gif"
    _save_gif(source, ["white", "#fefefe", "#fdfdfd"], [100, 200, 300])
    avatar_b = tmp_path / "avatar.webp"
    _save_gif(avatar_b, ["red", "blue"], [80, 120], size=(40, 10))
    avatar_a = tmp_path / "avatar-a.png"
    Image.new("RGBA", (10, 20), "green").save(avatar_a)
    output = tmp_path / "output.mp4"

    compose_mp4(
        source,
        {"keyframes": {"b": [{"t": 0, "x": 48, "y": 22, "w": 20, "h": 20}]}},
        avatar_a,
        avatar_b,
        output,
    )

    info = _probe(output)
    assert (int(info["width"]), int(info["height"])) == (96, 64)
    assert int(info["nb_frames"]) == 15
    assert float(info["duration"]) == pytest.approx(0.6, abs=0.02)
    frames = _raw_frames(output, (96, 64))
    assert len(frames) == 15
    sampled = [frames[index].getpixel((58, 32)) for index in (0, 2, 5, 6, 8, 10)]
    assert sampled[0][0] > sampled[0][2]
    assert sampled[1][2] > sampled[1][0]
    assert sampled[2][0] > sampled[2][2]
    assert sampled[3][0] > sampled[3][2]
    assert sampled[4][2] > sampled[4][0]
    assert sampled[5][0] > sampled[5][2]


def test_compose_scales_keyframes_before_overlay(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (960, 480), "white").save(source)
    avatar_a = tmp_path / "avatar-a.png"
    Image.new("RGBA", (10, 10), "red").save(avatar_a)
    avatar_b = tmp_path / "avatar-b.png"
    Image.new("RGBA", (10, 10), "blue").save(avatar_b)
    output = tmp_path / "output.mp4"

    compose_mp4(
        source,
        {"keyframes": {"b": [{"t": 0, "x": 480, "y": 240, "w": 100, "h": 100}]}},
        avatar_a,
        avatar_b,
        output,
    )

    info = _probe(output)
    assert (int(info["width"]), int(info["height"])) == (480, 240)
    frame = _raw_frames(output, (480, 240))[0]
    red, green, blue = frame.getpixel((265, 135))
    assert blue > red + 40
    assert blue > green + 40


@pytest.mark.parametrize(
    "annotation",
    [
        {"keyframes": {"a": [{"t": 0, "x": 0, "y": 0, "w": math.inf, "h": 2}]}},
        {"keyframes": {"b": [{"t": 0, "x": 0, "y": 0, "w": 10**9, "h": 2}]}},
        {"keyframes": {"a": [{"t": 1.5, "x": 0, "y": 0, "w": 2, "h": 2}]}},
    ],
)
def test_compose_rejects_malformed_annotation(tmp_path, annotation):
    source = tmp_path / "source.png"
    Image.new("RGBA", (96, 64), "white").save(source)
    avatar = tmp_path / "avatar.png"
    Image.new("RGBA", (8, 8), "white").save(avatar)
    output = tmp_path / "output.mp4"

    with pytest.raises(ValueError, match="annotation"):
        compose_mp4(source, annotation, avatar, avatar, output)

    assert not output.exists()


def test_compose_rejects_real_dimensions_above_limit(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (2049, 2049), "white").save(source, optimize=True)
    avatar = tmp_path / "avatar.png"
    Image.new("RGBA", (8, 8), "white").save(avatar)

    with pytest.raises(RenderError, match="пикселей"):
        compose_mp4(source, {}, avatar, avatar, tmp_path / "output.mp4")


async def test_long_video_renders_without_retaining_all_frames(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=1280x720:rate=10:duration=15",
            "-frames:v", "150", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            "-threads", "1", str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    avatar = Image.new("RGBA", (16, 16), "white")
    output = tmp_path / "output.mp4"
    result = await run_render_job(source, {}, avatar, avatar, output)

    assert result["frames"] == 375
    assert result["duration_ms"] == 15000
    assert result["peak_rss_kib"] < 256 * 1024
    video = _probe(output)
    assert (video["width"], video["height"]) == (480, 270)
    assert int(video["nb_frames"]) == 375
    assert float(video["duration"]) == pytest.approx(15, abs=0.02)


def test_worker_rejects_allocation_above_memory_limit():
    script = """
from steward.helpers.fuck_renderer import DATA_MEMORY_LIMIT_BYTES, _set_memory_limits
_set_memory_limits()
try:
    buffer = bytearray(DATA_MEMORY_LIMIT_BYTES)
except MemoryError:
    raise SystemExit(0)
raise SystemExit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_compose_preserves_video_display_rotation(tmp_path):
    original = tmp_path / "original.mp4"
    source = tmp_path / "rotated.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=320x240:rate=25:duration=1",
            "-threads", "1", str(original),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-display_rotation", "90", "-i", str(original),
            "-c", "copy", str(source),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    avatar = tmp_path / "avatar.png"
    Image.new("RGBA", (8, 8), "white").save(avatar)
    output = tmp_path / "output.mp4"

    compose_mp4(source, {}, avatar, avatar, output)

    video = _probe(output)
    assert (video["width"], video["height"]) == (240, 320)


def test_compose_preserves_transparent_avatar_pixels(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (96, 64), "white").save(source)
    avatar = tmp_path / "avatar.png"
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(avatar)
    output = tmp_path / "output.mp4"

    compose_mp4(
        source,
        {"keyframes": {"b": [{"t": 0, "x": 32, "y": 16, "w": 32, "h": 32}]}},
        avatar,
        avatar,
        output,
    )

    pixel = _raw_frames(output, (96, 64))[0].getpixel((48, 32))
    assert all(channel > 230 for channel in pixel)
