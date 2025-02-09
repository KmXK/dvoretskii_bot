from typing import Any

import pyrate_limiter
from pyrate_limiter import Limiter, Rate


class Duration:
    SECOND = pyrate_limiter.Duration.SECOND
    MINUTE = pyrate_limiter.Duration.MINUTE
    HOUR = pyrate_limiter.Duration.HOUR


# TODO: Move to bot context
limiters: dict[Any, Limiter] = {}


def get_limiter(obj: Any, limit: int, duration: pyrate_limiter.Duration) -> Limiter:
    if obj not in limiters:
        limiters[obj] = Limiter(Rate(limit, duration))
    return limiters[obj]


def check_limit(obj: Any, limit: int, duration: pyrate_limiter.Duration):
    limiter = get_limiter(obj, limit, duration)
    return limiter.try_acquire("", 1)


def limit(limit: int, duration: pyrate_limiter.Duration) -> Any:
    def mapping(*args, **kwargs):
        return "", 1

    return Limiter(Rate(limit, duration)).as_decorator()(mapping)  # type: ignore
