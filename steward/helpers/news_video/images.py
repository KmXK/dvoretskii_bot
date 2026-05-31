"""Image fetcher for slides — DuckDuckGo image search, with meme-query suffix when needed."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}


def _ddg_search(query: str, max_results: int = 8) -> list[dict]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        return list(ddgs.images(query, max_results=max_results, safesearch="moderate"))


async def _download(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_HEADERS
        ) as client:
            resp = await client.get(url)
        if resp.status_code == 200 and len(resp.content) > 5_000:
            return resp.content
    except Exception:
        return None
    return None


async def search_image(query: str, is_meme: bool = False) -> bytes | None:
    q = f"{query} meme" if is_meme else query
    try:
        results = await asyncio.to_thread(_ddg_search, q, 8)
    except Exception:
        logger.exception("DDG search failed: %s", q)
        return None
    for r in results:
        url = r.get("image")
        if not url:
            continue
        data = await _download(url)
        if data is not None:
            return data
    return None


async def fetch_slides(
    queries: list[tuple[str, bool]], dst_dir: Path
) -> list[Path | None]:
    """Fetch one image per query in parallel. Returns list of paths (None on failure)."""
    dst_dir.mkdir(parents=True, exist_ok=True)

    async def one(i: int, q: str, is_meme: bool) -> Path | None:
        data = await search_image(q, is_meme=is_meme)
        if data is None:
            logger.warning("no image for query %r (meme=%s)", q, is_meme)
            return None
        path = dst_dir / f"slide_{i:02d}.jpg"
        path.write_bytes(data)
        return path

    return await asyncio.gather(
        *(one(i, q, m) for i, (q, m) in enumerate(queries))
    )
