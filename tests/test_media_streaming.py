import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from steward.helpers.media import fetch_tg_file_to


@pytest.fixture(autouse=True)
def clear_download_proxy(monkeypatch):
    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)


class _Bot:
    token = "test-token"

    def __init__(self, file_path: str, file_size: int | None = None):
        self.file = SimpleNamespace(file_path=file_path, file_size=file_size)

    async def get_file(self, file_id: str):
        return self.file


@asynccontextmanager
async def _streaming_endpoint(chunks: list[bytes], gate: asyncio.Event | None = None):
    async def handle(request):
        response = web.StreamResponse()
        await response.prepare(request)
        for chunk in chunks:
            await response.write(chunk)
        if gate is not None:
            await gate.wait()
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/file", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/file"
    finally:
        if gate is not None:
            gate.set()
        await runner.cleanup()


async def _wait_for_nonempty_file(path: Path) -> None:
    for _ in range(100):
        if path.exists() and path.stat().st_size:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("download did not write a chunk")


@pytest.mark.asyncio
async def test_fetch_tg_file_to_streams_chunked_response(tmp_path):
    payload = [b"first-", b"second-", b"third"]
    async with _streaming_endpoint(payload) as url:
        dest = tmp_path / "media.bin"
        result = await fetch_tg_file_to(
            _Bot(url),
            "file-id",
            dest,
            max_bytes=sum(map(len, payload)),
        )

    assert result == dest
    assert dest.read_bytes() == b"".join(payload)


@pytest.mark.asyncio
async def test_fetch_tg_file_to_removes_partial_file_on_actual_limit(tmp_path):
    payload = [b"first-", b"second-", b"third"]
    async with _streaming_endpoint(payload) as url:
        dest = tmp_path / "media.bin"
        with pytest.raises(ValueError, match="Размер файла Telegram"):
            await fetch_tg_file_to(_Bot(url), "file-id", dest, max_bytes=5)

    assert not dest.exists()


@pytest.mark.asyncio
async def test_fetch_tg_file_to_removes_partial_file_on_cancellation(tmp_path):
    gate = asyncio.Event()
    async with _streaming_endpoint([b"x" * 65536], gate) as url:
        dest = tmp_path / "media.bin"
        task = asyncio.create_task(fetch_tg_file_to(_Bot(url), "file-id", dest))
        await _wait_for_nonempty_file(dest)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert not dest.exists()
