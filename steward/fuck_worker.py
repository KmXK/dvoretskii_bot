from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
from pathlib import Path

from aiohttp import web

JOBS_DIR = Path("data/fuck_jobs")
ASSETS_DIR = Path("data/fuck")
RENDER_TIMEOUT = 60
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def _job_directory(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Неверный идентификатор рендера.")

    return JOBS_DIR / job_id


def _render(job_id: str) -> int:
    from steward.helpers.fuck_renderer import compose_mp4

    job_dir = _job_directory(job_id)
    try:
        manifest_path = job_dir / "manifest.json"
        if manifest_path.stat().st_size > 64 * 1024:
            raise ValueError("Разметка шаблона слишком большая.")

        manifest = json.loads(manifest_path.read_text())
        source = (ASSETS_DIR / manifest["source"]).resolve()
        source.relative_to(ASSETS_DIR.resolve())
        compose_mp4(
            source,
            manifest["annotation"],
            job_dir / "a.media",
            job_dir / "b.media",
            job_dir / "output.mp4",
        )
        return 0
    except ValueError as error:
        (job_dir / "error.json").write_text(json.dumps({"error": str(error)[:500]}))
        return 1
    except Exception:
        (job_dir / "error.json").write_text(json.dumps({"error": "Не получилось сгенерить гифку."}))
        return 1


async def _stop_process(process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    await process.wait()


async def _stop_job(start_task) -> None:
    try:
        process = await asyncio.shield(start_task)
    except Exception:
        return

    await _stop_process(process)


async def _finish_job(start_task) -> None:
    cleanup = asyncio.create_task(_stop_job(start_task))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            pass

    cleanup.result()


async def handle_render(request: web.Request) -> web.Response:
    active = request.app["active_jobs"]
    if active:
        return web.json_response({"error": "Рендер занят, попробуй чуть позже."}, status=409)

    try:
        body = await request.json()
        job_id = body["job_id"]
        job_dir = _job_directory(job_id)
        if not (job_dir / "manifest.json").is_file():
            raise ValueError("Задание рендера не найдено.")
    except (ValueError, KeyError, TypeError):
        return web.json_response({"error": "Неверное задание рендера."}, status=400)

    start_task = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "steward.fuck_worker",
        "--render",
        job_id,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    ))
    active[job_id] = start_task
    try:
        process = await asyncio.shield(start_task)
        await asyncio.wait_for(process.wait(), timeout=RENDER_TIMEOUT)
        output = job_dir / "output.mp4"
        if process.returncode == 0 and output.is_file() and 0 < output.stat().st_size <= MAX_OUTPUT_BYTES:
            return web.json_response({"ok": True})

        error_path = job_dir / "error.json"
        if error_path.is_file() and error_path.stat().st_size <= 4096:
            return web.json_response(json.loads(error_path.read_text()), status=422)

        return web.json_response({"error": "Рендер прерван, попробуй другую гифку."}, status=422)
    except TimeoutError:
        return web.json_response({"error": "Генерация заняла слишком долго, попробуй другую гифку."}, status=504)
    finally:
        await _finish_job(start_task)
        active.pop(job_id, None)


async def handle_cancel(request: web.Request) -> web.Response:
    start_task = request.app["active_jobs"].get(request.match_info["job_id"])
    if start_task is not None:
        await _finish_job(start_task)

    return web.json_response({"ok": True})


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def _cleanup(app: web.Application) -> None:
    for start_task in tuple(app["active_jobs"].values()):
        await _finish_job(start_task)


def create_app() -> web.Application:
    app = web.Application(client_max_size=1024)
    app["active_jobs"] = {}
    app.router.add_post("/render", handle_render)
    app.router.add_delete("/render/{job_id}", handle_cancel)
    app.router.add_get("/health", handle_health)
    app.on_cleanup.append(_cleanup)
    return app


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--render":
        sys.exit(_render(sys.argv[2]))

    web.run_app(create_app(), host="0.0.0.0", port=8091, handler_cancellation=True)
