import asyncio
import json
import signal

import pytest
from PIL import Image

import steward.helpers.fuck_render_job as render_job


def make_images():
    return Image.new("RGBA", (8, 8), "red"), Image.new("RGBA", (8, 8), "blue")


class CompletedProcess:
    pid = 101
    returncode = 0

    def __init__(self, stdout=b"{}", stderr=b""):
        self.stdout = stdout
        self.stderr = stderr
        self.communicate_calls = 0

    async def communicate(self):
        self.communicate_calls += 1
        return self.stdout, self.stderr


class WaitingProcess:
    pid = 202
    returncode = None
    exit_signal = signal.SIGTERM

    def __init__(self):
        self.communicate_started = asyncio.Event()
        self.communicate_finished = asyncio.Event()
        self.release = asyncio.Event()

    async def communicate(self):
        self.communicate_started.set()
        await self.release.wait()
        self.returncode = -self.exit_signal
        self.communicate_finished.set()
        return b"", b""


async def call_job(tmp_path, monkeypatch, process):
    calls = []

    async def create_process(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(
        render_job.asyncio,
        "create_subprocess_exec",
        create_process,
    )
    avatar_a, avatar_b = make_images()
    result = await render_job.run_render_job(
        tmp_path / "source.gif",
        {"keyframes": {}},
        avatar_a,
        avatar_b,
        tmp_path / "output.mp4",
    )
    return result, calls


async def test_run_render_job_returns_worker_summary_and_limits_threads(
    tmp_path,
    monkeypatch,
):
    summary = {
        "frames": 4,
        "width": 94,
        "height": 66,
        "duration_ms": 600,
        "peak_rss_kib": 1234,
    }
    process = CompletedProcess(json.dumps(summary).encode())
    result, calls = await call_job(tmp_path, monkeypatch, process)

    args, kwargs = calls[0]
    assert result == summary
    assert args[:3] == (
        render_job.sys.executable,
        "-m",
        "steward.helpers.fuck_renderer",
    )
    assert kwargs["start_new_session"] is True
    assert all(kwargs["env"][name] == "1" for name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ))
    assert kwargs["env"]["IMAGEIO_FFMPEG_NO_PREVENT_SIGINT"] == "1"
    assert kwargs["env"]["IMAGEIO_FFMPEG_EXE"] == "ffmpeg"
    assert process.communicate_calls == 1


async def test_timeout_kills_process_group_and_waits_for_exit(
    tmp_path,
    monkeypatch,
):
    process = WaitingProcess()
    killed = asyncio.Event()

    def killpg(pid, sig):
        assert (pid, sig) == (process.pid, signal.SIGTERM)
        killed.set()
        process.release.set()

    monkeypatch.setattr(render_job.os, "killpg", killpg)
    monkeypatch.setattr(render_job, "RENDER_TIMEOUT_SECONDS", 0)

    async def create_process(*_args, **_kwargs):
        return process

    monkeypatch.setattr(
        render_job.asyncio,
        "create_subprocess_exec",
        create_process,
    )
    avatar_a, avatar_b = make_images()

    with pytest.raises(TimeoutError):
        await render_job.run_render_job(
            tmp_path / "source.gif",
            {},
            avatar_a,
            avatar_b,
            tmp_path / "output.mp4",
        )

    assert killed.is_set()
    assert process.communicate_finished.is_set()
    assert process.returncode == -signal.SIGTERM


async def test_cancellation_kills_process_group_before_returning(
    tmp_path,
    monkeypatch,
):
    process = WaitingProcess()
    killed = asyncio.Event()

    def killpg(pid, sig):
        assert (pid, sig) == (process.pid, signal.SIGTERM)
        killed.set()

    monkeypatch.setattr(render_job.os, "killpg", killpg)

    async def create_process(*_args, **_kwargs):
        return process

    monkeypatch.setattr(
        render_job.asyncio,
        "create_subprocess_exec",
        create_process,
    )
    avatar_a, avatar_b = make_images()
    task = asyncio.create_task(
        render_job.run_render_job(
            tmp_path / "source.gif",
            {},
            avatar_a,
            avatar_b,
            tmp_path / "output.mp4",
        )
    )
    await process.communicate_started.wait()
    task.cancel()
    await asyncio.wait_for(killed.wait(), timeout=1)
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert not process.communicate_finished.is_set()
    process.release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.communicate_finished.is_set()


async def test_timeout_escalates_if_worker_does_not_stop(tmp_path, monkeypatch):
    process = WaitingProcess()
    signals = []

    def killpg(pid, sig):
        assert pid == process.pid
        signals.append(sig)
        if sig == signal.SIGKILL:
            process.exit_signal = sig
            process.release.set()

    monkeypatch.setattr(render_job.os, "killpg", killpg)
    monkeypatch.setattr(render_job, "RENDER_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(render_job, "RENDER_STOP_TIMEOUT_SECONDS", 0)

    with pytest.raises(TimeoutError):
        await call_job(tmp_path, monkeypatch, process)

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert process.communicate_finished.is_set()
