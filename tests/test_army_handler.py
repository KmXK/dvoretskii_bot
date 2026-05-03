"""Tests for ArmyFeature: view, add, remove."""
import datetime

from steward.data.models.army import Army
from steward.features.army import ArmyFeature
from tests.conftest import DEFAULT_USER_ID, invoke, make_repository


def _army(name: str, days_left: int = 100) -> Army:
    now = datetime.datetime.now()
    start = now - datetime.timedelta(days=200)
    end = now + datetime.timedelta(days=days_left)
    return Army(name=name, start_date=start.timestamp(), end_date=end.timestamp())


class TestArmyView:
    async def test_empty(self):
        repo = make_repository()
        reply, ok = await invoke(ArmyFeature, "/army", repo)
        assert ok
        assert "никого" in reply

    async def test_shows_army_members(self):
        repo = make_repository()
        repo.db.army = [_army("Иван"), _army("Пётр")]
        reply, ok = await invoke(ArmyFeature, "/army", repo)
        assert ok
        assert "Иван" in reply
        assert "Пётр" in reply


class TestArmyAdd:
    async def test_adds_member(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, _ = await invoke(ArmyFeature, "/army add Иван 01.01.2024 01.01.2026", repo)
        assert len(repo.db.army) == 1
        assert repo.db.army[0].name == "Иван"
        assert "Добавил" in reply


class TestArmyRemove:
    async def test_removes_member(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.army = [_army("Иван")]
        reply, _ = await invoke(ArmyFeature, "/army remove Иван", repo)
        assert len(repo.db.army) == 0
        assert "Удалил" in reply

    async def test_not_found(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, _ = await invoke(ArmyFeature, "/army remove Иван", repo)
        assert "не существует" in reply
        assert len(repo.db.army) == 0
