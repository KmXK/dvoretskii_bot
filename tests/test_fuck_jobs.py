import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from steward.helpers import fuck_jobs


def _context():
    return SimpleNamespace(bot=SimpleNamespace(send_animation=AsyncMock()), chat_id=123)


async def test_full_queue_does_not_download_or_create_job(monkeypatch, tmp_path):
    monkeypatch.setattr(fuck_jobs, "_ADMITTED_JOBS", 3)
    monkeypatch.setattr(fuck_jobs, "JOBS_DIR", tmp_path / "jobs")
    prepare = AsyncMock()
    monkeypatch.setattr(fuck_jobs, "_prepare_and_send", prepare)

    with pytest.raises(ValueError, match="Рендер занят"):
        await fuck_jobs.render_and_send(_context(), Path("template.gif"), {}, 1, None, 2, None)

    prepare.assert_not_awaited()
    assert fuck_jobs._ADMITTED_JOBS == 3
    assert not fuck_jobs.JOBS_DIR.exists()


async def test_cancelled_waiter_releases_admission_without_starting_render(monkeypatch):
    monkeypatch.setattr(fuck_jobs, "_ADMITTED_JOBS", 0)
    semaphore = asyncio.Semaphore(0)
    monkeypatch.setattr(fuck_jobs, "_RENDER_SEMAPHORE", semaphore)
    prepare = AsyncMock()
    monkeypatch.setattr(fuck_jobs, "_prepare_and_send", prepare)
    task = asyncio.create_task(
        fuck_jobs.render_and_send(_context(), Path("template.gif"), {}, 1, None, 2, None)
    )
    await asyncio.sleep(0)
    assert fuck_jobs._ADMITTED_JOBS == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fuck_jobs._ADMITTED_JOBS == 0
    prepare.assert_not_awaited()


async def test_render_failure_cleans_job_and_releases_slot(monkeypatch, tmp_path):
    monkeypatch.setattr(fuck_jobs, "_ADMITTED_JOBS", 0)
    monkeypatch.setattr(fuck_jobs, "_RENDER_SEMAPHORE", asyncio.Semaphore(1))
    monkeypatch.setattr(fuck_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(fuck_jobs, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(fuck_jobs, "_save_participant", AsyncMock())
    monkeypatch.setattr(fuck_jobs, "_render_job", AsyncMock(side_effect=ValueError("Рендер прерван")))

    with pytest.raises(ValueError, match="Рендер прерван"):
        await fuck_jobs.render_and_send(
            _context(),
            fuck_jobs.ASSETS_DIR / "template.gif",
            {},
            1,
            None,
            2,
            None,
        )

    assert fuck_jobs._ADMITTED_JOBS == 0
    assert not list(fuck_jobs.JOBS_DIR.iterdir())


async def test_oversized_attachment_rejected_before_avatar_download(monkeypatch, tmp_path):
    monkeypatch.setattr(fuck_jobs, "_ADMITTED_JOBS", 0)
    monkeypatch.setattr(fuck_jobs, "_RENDER_SEMAPHORE", asyncio.Semaphore(1))
    monkeypatch.setattr(fuck_jobs, "JOBS_DIR", tmp_path / "jobs")
    save = AsyncMock()
    monkeypatch.setattr(fuck_jobs, "_save_participant", save)
    media = SimpleNamespace(file_size=fuck_jobs.MAX_ATTACHMENT_BYTES + 1)

    with pytest.raises(ValueError, match="20 МБ"):
        await fuck_jobs.render_and_send(
            _context(),
            Path("template.gif"),
            {},
            1,
            None,
            2,
            None,
            b_media=media,
        )

    save.assert_not_awaited()
    assert not fuck_jobs.JOBS_DIR.exists()
    assert fuck_jobs._ADMITTED_JOBS == 0


def test_stale_jobs_are_removed_without_touching_recent_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(fuck_jobs, "JOBS_DIR", tmp_path)
    stale = tmp_path / ("a" * 32)
    recent = tmp_path / ("b" * 32)
    stale.mkdir()
    recent.mkdir()
    (stale / "b.media").write_bytes(b"old")
    old_time = time.time() - 7200
    os.utime(stale, (old_time, old_time))

    fuck_jobs._remove_stale_jobs()

    assert not stale.exists()
    assert recent.exists()
