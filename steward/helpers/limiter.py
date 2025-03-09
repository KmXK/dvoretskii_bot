from enum import IntEnum
from inspect import isawaitable
from typing import Any

import pyrate_limiter
from pyrate_limiter import ItemMapping, Limiter, Rate


class Duration(IntEnum):
    SECOND = 1000
    MINUTE = 60 * SECOND
    HOUR = 60 * MINUTE


# TODO: Move to bot context
limiters: dict[Any, Limiter] = {}


def get_rate_limiter(
    obj: Any,
    limit: int,
    duration: int | Duration,
) -> Limiter:
    if obj not in limiters:
        limiters[obj] = Limiter(Rate(limit, int(duration)))
    return limiters[obj]


def check_limit(
    obj: Any,
    limit: int,
    duration: int | Duration,
    name: str = "",
    weight: int = 1,
) -> bool:
    limiter = get_rate_limiter(obj, limit, duration)
    result = limiter.try_acquire(name, weight)  # exception here
    assert not isawaitable(
        result
    )  # зависит от типа лимитера, у нас Rate, там всегда синхронно
    return result


def _simple_mapping(*args, **kwargs):
    return "", 1


def limit(limit: int, duration: pyrate_limiter.Duration, mapping: ItemMapping) -> Any:
    return Limiter(Rate(limit, duration)).as_decorator()(_simple_mapping)  # type: ignore
