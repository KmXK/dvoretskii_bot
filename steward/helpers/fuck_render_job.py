import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from PIL import Image


RENDER_TIMEOUT_SECONDS = 30
RENDER_STOP_TIMEOUT_SECONDS = 3
MIN_AVAILABLE_MEMORY_BYTES = 2 * 1024 * 1024 * 1024


def available_memory_bytes() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            available = int(line.split()[1]) * 1024
            break
    else:
        raise RuntimeError("MemAvailable is unavailable")

    memory_max = Path("/sys/fs/cgroup/memory.max")
    memory_current = Path("/sys/fs/cgroup/memory.current")
    if memory_max.exists() and memory_current.exists():
        limit = memory_max.read_text().strip()
        if limit != "max":
            available = min(available, int(limit) - int(memory_current.read_text()))

    return max(0, available)


def _write_job(
    source_path: Path,
    annotation: dict,
    avatar_a: Image.Image,
    avatar_b: Image.Image,
    output_path: Path,
) -> Path:
    avatar_paths = [output_path.parent / name for name in ("a.png", "b.png")]
    for avatar, path in zip((avatar_a, avatar_b), avatar_paths):
        with avatar.copy() as image:
            image.thumbnail((480, 480), Image.LANCZOS)
            image.save(path)

    job_path = output_path.parent / "job.json"
    job_path.write_text(json.dumps({
        "source_path": str(source_path.resolve()),
        "annotation": annotation,
        "avatar_a_path": str(avatar_paths[0]),
        "avatar_b_path": str(avatar_paths[1]),
        "output_path": str(output_path),
    }))
    return job_path


async def _kill_render(start_task, communication_task) -> None:
    process = await start_task
    if communication_task is None:
        communication_task = asyncio.create_task(process.communicate())

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    try:
        await asyncio.wait_for(
            asyncio.shield(communication_task),
            timeout=RENDER_STOP_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        await communication_task


async def run_render_job(
    source_path: Path,
    annotation: dict,
    avatar_a: Image.Image,
    avatar_b: Image.Image,
    output_path: Path,
) -> dict:
    job_path = _write_job(source_path, annotation, avatar_a, avatar_b, output_path)
    environment = os.environ.copy()
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[name] = "1"

    environment["IMAGEIO_FFMPEG_NO_PREVENT_SIGINT"] = "1"
    environment["IMAGEIO_FFMPEG_EXE"] = "ffmpeg"

    start_task = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "steward.helpers.fuck_renderer",
        str(job_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env=environment,
    ))
    communication_task = None
    try:
        process = await asyncio.shield(start_task)
        communication_task = asyncio.create_task(process.communicate())
        stdout, stderr = await asyncio.wait_for(
            asyncio.shield(communication_task),
            timeout=RENDER_TIMEOUT_SECONDS,
        )
    except BaseException:
        if not start_task.done() or not start_task.exception():
            cleanup = asyncio.create_task(_kill_render(start_task, communication_task))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    pass

            cleanup.result()

        raise

    if process.returncode:
        raise RuntimeError(
            f"Render worker exited with code {process.returncode}: "
            f"{stderr.decode(errors='replace')[-2000:]}"
        )

    return json.loads(stdout)
