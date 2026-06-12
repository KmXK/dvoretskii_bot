"""Кэш url -> file_id скачанных медиа. Общий для чатового и inline-флоу:
ссылка, уже скачанная в чате, отвечает на inline-запрос мгновенно
(и наоборот)."""

from dataclasses import dataclass
from typing import Literal

_CACHE_MAX = 200

MediaKind = Literal["video", "photo", "audio"]


@dataclass
class CachedMedia:
    file_id: str
    caption: str | None = None
    kind: MediaKind = "video"
    duration: float | None = None


_cache: dict[str, list[CachedMedia]] = {}


def get(url: str) -> list[CachedMedia] | None:
    return _cache.get(url)


def put(url: str, medias: list[CachedMedia]) -> None:
    if url not in _cache and len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[url] = medias
