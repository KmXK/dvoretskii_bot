import json
import shutil
import subprocess
import sys

import pytest
from PIL import Image

from steward.helpers.fuck_render_job import run_render_job


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)


def _probe(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,nb_frames,duration",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout)["streams"][0]


@pytest.mark.parametrize("extension", ["gif", "webp"])
async def test_animation_renders_with_original_total_duration(tmp_path, extension):
    source = tmp_path / f"source.{extension}"
    frames = [Image.new("RGB", (94, 66), color) for color in ("red", "green", "blue")]
    frames[0].save(
        source,
        save_all=True,
        append_images=frames[1:],
        duration=[100, 200, 300],
        loop=0,
        lossless=True,
    )
    avatar = Image.new("RGBA", (16, 16), "white")
    output = tmp_path / "output.mp4"
    annotation = {"keyframes": {"a": [{"t": 0, "x": 20, "y": 20, "w": 12, "h": 12}]}}
    result = await run_render_job(source, annotation, avatar, avatar, output)

    assert result["frames"] == 3
    assert result["duration_ms"] == 600
    assert result["peak_rss_kib"] < 512 * 1024
    video = _probe(output)
    assert (video["width"], video["height"]) == (94, 66)
    assert int(video["nb_frames"]) == 3
    assert float(video["duration"]) == pytest.approx(0.6, abs=0.02)


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
        timeout=10,
    )
    avatar = Image.new("RGBA", (16, 16), "white")
    output = tmp_path / "output.mp4"
    result = await run_render_job(source, {}, avatar, avatar, output)

    assert result["frames"] == 150
    assert result["duration_ms"] == 15000
    video = _probe(output)
    assert (video["width"], video["height"]) == (480, 270)
    assert int(video["nb_frames"]) == 150
    assert float(video["duration"]) == pytest.approx(15, abs=0.02)


async def test_actual_source_dimensions_override_annotation(tmp_path):
    source = tmp_path / "oversized.gif"
    Image.new("RGB", (4098, 2)).save(source)
    avatar = Image.new("RGBA", (16, 16), "white")
    output = tmp_path / "output.mp4"

    with pytest.raises(RuntimeError):
        await run_render_job(source, {"width": 10, "height": 10}, avatar, avatar, output)

    assert not output.exists()


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
