from typing import Any, Callable, Generic, Iterable, TypeVar

from steward.data.repository import Repository

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


def _matches(item: Any, kw: dict[str, Any]) -> bool:
    for field, expected in kw.items():
        if not hasattr(item, field):
            return False
        if getattr(item, field) != expected:
            return False
    return True


class _BaseCollection:
    def __init__(self, repository: Repository, attr: str):
        self._repository = repository
        self._attr = attr

    def _data(self) -> Any:
        return getattr(self._repository.db, self._attr)

    async def save(self) -> None:
        await self._repository.save()


class ListCollection(Generic[T], _BaseCollection):
    def __init__(self, repository: Repository, attr: str, id_field: str = "id"):
        super().__init__(repository, attr)
        self._id_field = id_field

    def all(self) -> list[T]:
        return list(self._data())

    def __iter__(self):
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())

    def filter(self, **kw: Any) -> list[T]:
        return [x for x in self._data() if _matches(x, kw)]

    def find_by(self, **kw: Any) -> T | None:
        for x in self._data():
            if _matches(x, kw):
                return x
        return None

    def find_one(self, predicate: Callable[[T], bool]) -> T | None:
        for x in self._data():
            if predicate(x):
                return x
        return None

    def next_id(self) -> int:
        return max((getattr(x, self._id_field, 0) or 0 for x in self._data()), default=0) + 1

    def add(self, item: T) -> T:
        if hasattr(item, self._id_field):
            current = getattr(item, self._id_field)
            if current is None or current == 0:
                setattr(item, self._id_field, self.next_id())
        self._data().append(item)
        return item

    def remove(self, item: T) -> None:
        self._data().remove(item)

    def remove_where(self, **kw: Any) -> int:
        items = self.filter(**kw)
        for item in items:
            self._data().remove(item)
        return len(items)

    def replace_all(self, items: Iterable[T]) -> None:
        data = self._data()
        data.clear()
        data.extend(items)

    def sort_by(self, key: Callable[[T], Any], reverse: bool = False) -> list[T]:
        return sorted(self._data(), key=key, reverse=reverse)


class SetCollection(Generic[T], _BaseCollection):
    def all(self) -> set[T]:
        return set(self._data())

    def __iter__(self):
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())

    def __contains__(self, item: T) -> bool:
        return item in self._data()

    def contains(self, item: T) -> bool:
        return item in self._data()

    def add(self, item: T) -> bool:
        if item in self._data():
            return False
        self._data().add(item)
        return True

    def remove(self, item: T) -> bool:
        if item not in self._data():
            return False
        self._data().remove(item)
        return True

    def add_many(self, items: Iterable[T]) -> list[T]:
        added = []
        for item in items:
            if self.add(item):
                added.append(item)
        return added

    def remove_many(self, items: Iterable[T]) -> list[T]:
        removed = []
        for item in items:
            if self.remove(item):
                removed.append(item)
        return removed


class DictCollection(Generic[K, V], _BaseCollection):
    def all(self) -> dict[K, V]:
        return dict(self._data())

    def get(self, key: K, default: V | None = None) -> V | None:
        return self._data().get(key, default)

    def set(self, key: K, value: V) -> None:
        self._data()[key] = value

    def pop(self, key: K, default: V | None = None) -> V | None:
        return self._data().pop(key, default)

    def contains(self, key: K) -> bool:
        return key in self._data()

    def __contains__(self, key: K) -> bool:
        return key in self._data()

    def __len__(self) -> int:
        return len(self._data())

    def keys(self):
        return self._data().keys()

    def values(self):
        return self._data().values()

    def items(self):
        return self._data().items()


class _CollectionDescriptor:
    def __init__(self, attr: str, id_field: str = "id"):
        self.attr = attr
        self.id_field = id_field

    def __set_name__(self, owner, name):
        self._owner_name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        repo: Repository = getattr(instance, "repository", None)
        if repo is None:
            raise RuntimeError(
                f"Collection '{self.attr}' accessed before repository injection on {owner.__name__}"
            )
        return _build_collection(repo, self.attr, self.id_field)


def collection(attr: str, *, id_field: str = "id") -> Any:
    return _CollectionDescriptor(attr, id_field)


def _build_collection(repository: Repository, attr: str, id_field: str) -> Any:
    if not hasattr(repository.db, attr):
        raise AttributeError(f"{type(repository.db).__name__} has no field '{attr}'")
    value = getattr(repository.db, attr)
    if isinstance(value, list):
        return ListCollection(repository, attr, id_field=id_field)
    if isinstance(value, set):
        return SetCollection(repository, attr)
    if isinstance(value, dict):
        return DictCollection(repository, attr)
    raise TypeError(
        f"Cannot build collection for {type(repository.db).__name__}.{attr!r}: "
        f"unsupported value type {type(value).__name__}"
    )


Collection = ListCollection
