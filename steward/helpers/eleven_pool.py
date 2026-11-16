import os
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
_COOLDOWN_SECONDS = 12 * 60 * 60
_current: dict[tuple[str, ...], int] = {}
_exhausted_until: dict[str, float] = {}


def eleven_keys(fallback: str | None = None) -> tuple[str, ...]:
    configured = os.environ.get("ELEVENLABS_API_KEYS", "")
    keys = tuple(dict.fromkeys(key.strip() for key in configured.split(",") if key.strip()))
    return keys or ((fallback,) if fallback else ())


def _quota_error(error: Exception) -> bool:
    body = getattr(error, "body", None)
    detail = body.get("detail", {}) if isinstance(body, dict) else {}
    if isinstance(detail, dict):
        if detail.get("code") in {"quota_exceeded", "insufficient_credits"}:
            return True
        if detail.get("status") in {"quota_exceeded", "insufficient_credits"}:
            return True
        if detail.get("type") == "payment_required":
            return True
    return getattr(error, "status_code", None) == 402


async def call_with_eleven_keys(
    call: Callable[[str], Awaitable[T]], fallback: str | None = None,
) -> T | None:
    keys = eleven_keys(fallback)
    if not keys:
        return None
    last_error = None
    start = _current.get(keys, 0) % len(keys)
    for offset in range(len(keys)):
        index = (start + offset) % len(keys)
        key = keys[index]
        if _exhausted_until.get(key, 0) > time.monotonic():
            continue
        try:
            result = await call(key)
        except Exception as error:
            if not _quota_error(error):
                raise
            _exhausted_until[key] = time.monotonic() + _COOLDOWN_SECONDS
            _current[keys] = (index + 1) % len(keys)
            last_error = error
            continue
        _current[keys] = index
        return result
    if last_error is not None:
        raise last_error
    raise RuntimeError("ElevenLabs quota exhausted for all configured keys")
