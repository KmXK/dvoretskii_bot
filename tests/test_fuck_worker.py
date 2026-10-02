import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from steward import fuck_worker


@pytest.fixture
def worker_job(tmp_path, monkeypatch):
    project_root = str(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("PYTHONPATH", project_root)
    monkeypatch.chdir(tmp_path)
    assets = tmp_path / "data/fuck"
    assets.mkdir(parents=True)
    Image.new("RGB", (96, 96), "white").save(assets / "template.gif")

    job_id = "a" * 32
    job_dir = tmp_path / "data/fuck_jobs" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text(json.dumps({
        "source": "template.gif",
        "annotation": {"keyframes": {"a": [], "b": [
            {"t": 0, "x": 32, "y": 32, "w": 32, "h": 32, "angle": 0},
        ]}},
    }))
    Image.new("RGB", (32, 32), "green").save(job_dir / "a.media", format="PNG")
    Image.new("RGB", (32, 32), "red").save(
        job_dir / "b.media",
        format="GIF",
        save_all=True,
        append_images=[Image.new("RGB", (32, 32), "blue")],
        duration=[100, 200],
        loop=0,
    )
    return job_id, job_dir


async def test_worker_renders_animation_through_http(worker_job):
    job_id, job_dir = worker_job
    app = fuck_worker.create_app()
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/render", json={"job_id": job_id})
        assert response.status == 200, await response.text()
        assert await response.json() == {"ok": True}
        assert 0 < (job_dir / "output.mp4").stat().st_size < fuck_worker.MAX_OUTPUT_BYTES
        assert not app["active_jobs"]


async def test_worker_timeout_kills_child_and_releases_slot(worker_job, monkeypatch):
    job_id, _ = worker_job
    monkeypatch.setattr(fuck_worker, "RENDER_TIMEOUT", 0.05)
    create_process = asyncio.create_subprocess_exec
    children = []

    async def sleeping_process(*args, **kwargs):
        process = await create_process(
            sys.executable,
            "-c",
            "import time; time.sleep(20)",
            **kwargs,
        )
        children.append(process)
        return process

    monkeypatch.setattr(fuck_worker.asyncio, "create_subprocess_exec", sleeping_process)
    app = fuck_worker.create_app()
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/render", json={"job_id": job_id})
        assert response.status == 504
        assert children[0].returncode < 0
        assert not app["active_jobs"]


async def test_worker_cancel_kills_active_render(worker_job, monkeypatch):
    job_id, _ = worker_job
    create_process = asyncio.create_subprocess_exec
    started = asyncio.Event()
    children = []

    async def sleeping_process(*args, **kwargs):
        process = await create_process(
            sys.executable,
            "-c",
            "import time; time.sleep(20)",
            **kwargs,
        )
        children.append(process)
        started.set()
        return process

    monkeypatch.setattr(fuck_worker.asyncio, "create_subprocess_exec", sleeping_process)
    app = fuck_worker.create_app()
    async with TestClient(TestServer(app)) as client:
        render = asyncio.create_task(client.post("/render", json={"job_id": job_id}))
        await asyncio.wait_for(started.wait(), timeout=5)
        response = await client.delete(f"/render/{job_id}")
        assert response.status == 200
        assert children[0].returncode < 0
        result = await render
        assert result.status == 422
        assert not app["active_jobs"]


async def test_worker_rejects_paths_outside_job_directory():
    async with TestClient(TestServer(fuck_worker.create_app())) as client:
        response = await client.post("/render", json={"job_id": "../../outside"})
        assert response.status == 400


async def test_cancel_during_process_start_waits_and_kills_child(worker_job, monkeypatch):
    job_id, _ = worker_job
    create_process = asyncio.create_subprocess_exec
    starting = asyncio.Event()
    launch = asyncio.Event()
    children = []

    async def delayed_start(*args, **kwargs):
        starting.set()
        await launch.wait()
        process = await create_process(
            sys.executable,
            "-c",
            "import time; time.sleep(20)",
            **kwargs,
        )
        children.append(process)
        return process

    monkeypatch.setattr(fuck_worker.asyncio, "create_subprocess_exec", delayed_start)
    app = fuck_worker.create_app()
    async with TestClient(TestServer(app)) as client:
        render = asyncio.create_task(client.post("/render", json={"job_id": job_id}))
        await asyncio.wait_for(starting.wait(), timeout=5)
        cancel = asyncio.create_task(client.delete(f"/render/{job_id}"))
        await asyncio.sleep(0)
        launch.set()
        response = await cancel
        assert response.status == 200
        result = await render
        assert result.status == 422
        assert children[0].returncode < 0
        assert not app["active_jobs"]
