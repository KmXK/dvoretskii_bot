from inspect import isawaitable
from typing import Any

import pyrate_limiter
from pyrate_limiter import ItemMapping, Limiter, Rate


class Duration:
    SECOND = pyrate_limiter.Duration.SECOND
    MINUTE = pyrate_limiter.Duration.MINUTE
    HOUR = pyrate_limiter.Duration.HOUR


# TODO: Move to bot context
limiters: dict[Any, Limiter] = {}


def get_rate_limiter(
    obj: Any,
    limit: int,
    duration: pyrate_limiter.Duration,
) -> Limiter:
    if obj not in limiters:
        limiters[obj] = Limiter(Rate(limit, duration))
    return limiters[obj]


def check_limit(
    obj: Any,
    limit: int,
    duration: pyrate_limiter.Duration,
    name: str = "",
    weight: int = 1,
) -> bool:
    limiter = get_rate_limiter(obj, limit, duration)
    result = limiter.try_acquire(name, weight)
    assert not isawaitable(
        result
    )  # зависит от типа лимитера, у нас Rate, там всегда синхронно
    return result


def _simple_mapping(*args, **kwargs):
    return "", 1


def limit(limit: int, duration: pyrate_limiter.Duration, mapping: ItemMapping) -> Any:
    return Limiter(Rate(limit, duration)).as_decorator()(_simple_mapping)  # type: ignore
