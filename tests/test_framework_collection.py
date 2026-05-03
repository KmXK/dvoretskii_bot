from dataclasses import dataclass, field

import pytest

from steward.framework.collection import (
    DictCollection,
    ListCollection,
    SetCollection,
    _build_collection,
)


@dataclass
class FakeItem:
    id: int = 0
    name: str = ""


class FakeRepo:
    def __init__(self):
        self.db = _FakeDb()
        self._saves = 0

    async def save(self):
        self._saves += 1


@dataclass
class _FakeDb:
    items: list = field(default_factory=list)
    admin_ids: set = field(default_factory=set)
    bag: dict = field(default_factory=dict)


def test_list_add_assigns_id():
    repo = FakeRepo()
    coll: ListCollection[FakeItem] = ListCollection(repo, "items")
    item = coll.add(FakeItem(name="a"))
    assert item.id == 1
    item2 = coll.add(FakeItem(name="b"))
    assert item2.id == 2


def test_list_find_by():
    repo = FakeRepo()
    coll: ListCollection[FakeItem] = ListCollection(repo, "items")
    coll.add(FakeItem(name="a"))
    coll.add(FakeItem(name="b"))
    found = coll.find_by(name="b")
    assert found is not None and found.name == "b"
    assert coll.find_by(name="x") is None


def test_list_remove_where():
    repo = FakeRepo()
    coll: ListCollection[FakeItem] = ListCollection(repo, "items")
    coll.add(FakeItem(name="a"))
    coll.add(FakeItem(name="b"))
    coll.add(FakeItem(name="b"))
    n = coll.remove_where(name="b")
    assert n == 2
    assert len(coll) == 1


def test_set_add_returns_bool():
    repo = FakeRepo()
    coll: SetCollection[int] = SetCollection(repo, "admin_ids")
    assert coll.add(5) is True
    assert coll.add(5) is False
    assert 5 in coll
    assert coll.contains(5) is True


def test_set_remove_returns_bool():
    repo = FakeRepo()
    coll: SetCollection[int] = SetCollection(repo, "admin_ids")
    coll.add(1)
    assert coll.remove(1) is True
    assert coll.remove(1) is False


def test_set_add_many():
    repo = FakeRepo()
    coll: SetCollection[str] = SetCollection(repo, "admin_ids")  # type intentionally mismatched at runtime
    added = coll.add_many(["a", "b", "a", "c"])
    assert added == ["a", "b", "c"]


def test_dict_basic():
    repo = FakeRepo()
    coll: DictCollection[str, int] = DictCollection(repo, "bag")
    coll.set("x", 1)
    assert coll.get("x") == 1
    assert coll.get("y") is None
    assert coll.pop("x") == 1
    assert "x" not in coll


@pytest.mark.asyncio
async def test_save_calls_repo():
    repo = FakeRepo()
    coll = ListCollection(repo, "items")
    await coll.save()
    assert repo._saves == 1


def test_build_collection_chooses_type():
    repo = FakeRepo()
    assert isinstance(_build_collection(repo, "items", "id"), ListCollection)
    assert isinstance(_build_collection(repo, "admin_ids", "id"), SetCollection)
    assert isinstance(_build_collection(repo, "bag", "id"), DictCollection)
