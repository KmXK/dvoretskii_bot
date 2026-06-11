"""Кэш url -> file_id скачанных видео. Общий для чатового и inline-флоу:
ссылка, уже скачанная в чате, отвечает на inline-запрос мгновенно
(и наоборот)."""

from dataclasses import dataclass

_CACHE_MAX = 200


@dataclass
class CachedVideo:
    file_id: str
    caption: str | None


_cache: dict[str, CachedVideo] = {}


def get(url: str) -> CachedVideo | None:
    return _cache.get(url)


def put(url: str, video: CachedVideo) -> None:
    if url not in _cache and len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[url] = video
