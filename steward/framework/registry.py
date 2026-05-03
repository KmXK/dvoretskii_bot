from typing import Iterable

from steward.framework.feature import Feature
from steward.handlers.handler import Handler


class _Bucket:
    def __init__(self, name: str):
        self.name = name
        self.list: list[type[Handler]] = []

    def add(self, handler: type[Handler]) -> "_Bucket":
        self.list.append(handler)
        return self

    def add_many(self, handlers: Iterable[type[Handler]]) -> "_Bucket":
        for h in handlers:
            self.list.append(h)
        return self

    def __lshift__(self, handlers: Iterable[type[Handler]] | type[Handler]) -> "_Bucket":
        if isinstance(handlers, type):
            return self.add(handlers)
        return self.add_many(handlers)


def bucket(name: str) -> _Bucket:
    return _Bucket(name)


def init_features(buckets: list[_Bucket]) -> list[Handler]:
    instances: list[Handler] = []
    for b in buckets:
        for cls in b.list:
            instances.append(cls())
    return instances
