"""Tests for army handlers: view, add, remove."""
import datetime

from steward.data.models.army import Army
from tests.conftest import invoke, make_repository


def _army(name: str, days_left: int = 100) -> Army:
    now = datetime.datetime.now()
    start = now - datetime.timedelta(days=200)
    end = now + datetime.timedelta(days=days_left)
    return Army(name=name, start_date=start.timestamp(), end_date=end.timestamp())


class TestArmyViewHandler:
    async def test_empty(self):
        from steward.handlers.army_handler import ArmyViewHandler

        repo = make_repository()
        reply, ok = await invoke(ArmyViewHandler, "/army", repo)
        assert ok
        assert "никого" in reply

    async def test_shows_army_members(self):
        from steward.handlers.army_handler import ArmyViewHandler

        repo = make_repository()
        repo.db.army = [_army("Иван"), _army("Пётр")]
        reply, ok = await invoke(ArmyViewHandler, "/army", repo)
        assert ok
        assert "Иван" in reply
        assert "Пётр" in reply

    async def test_ignores_add_subcommand(self):
        from steward.handlers.army_handler import ArmyViewHandler

        repo = make_repository()
        _, ok = await invoke(ArmyViewHandler, "/army add Иван 01.01.2024 01.01.2026", repo)
        assert not ok

    async def test_ignores_remove_subcommand(self):
        from steward.handlers.army_handler import ArmyViewHandler

        repo = make_repository()
        _, ok = await invoke(ArmyViewHandler, "/army remove Иван", repo)
        assert not ok


class TestArmyAddHandler:
    async def test_adds_member(self):
        from steward.handlers.army_handler import ArmyAddHandler

        repo = make_repository()
        reply, _ = await invoke(ArmyAddHandler, "/army add Иван 01.01.2024 01.01.2026", repo)
        assert len(repo.db.army) == 1
        assert repo.db.army[0].name == "Иван"
        assert "Добавил" in reply


class TestArmyRemoveHandler:
    async def test_removes_member(self):
        from steward.handlers.army_handler import ArmyRemoveHandler

        repo = make_repository()
        repo.db.army = [_army("Иван")]
        reply, _ = await invoke(ArmyRemoveHandler, "/army remove Иван", repo)
        assert len(repo.db.army) == 0
        assert "Удалил" in reply

    async def test_not_found(self):
        from steward.handlers.army_handler import ArmyRemoveHandler

        repo = make_repository()
        reply, _ = await invoke(ArmyRemoveHandler, "/army remove Иван", repo)
        assert "не существует" in reply
        assert len(repo.db.army) == 0
