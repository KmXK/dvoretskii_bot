from typing import Any

import pyrate_limiter
from pyrate_limiter import Limiter, Rate


class Duration:
    SECOND = pyrate_limiter.Duration.SECOND
    MINUTE = pyrate_limiter.Duration.MINUTE
    HOUR = pyrate_limiter.Duration.HOUR


# TODO: Move to bot context
limiters: dict[Any, Limiter] = {}


def limit(limit: int, duration: pyrate_limiter.Duration) -> Any:
    def mapping(*args, **kwargs):
        return "", 1

    return Limiter(Rate(limit, duration)).as_decorator()(mapping)  # type: ignore
