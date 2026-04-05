"""Tests for admin handlers: view, add, remove."""
import pytest

from tests.conftest import invoke, make_repository


class TestAdminView:
    async def test_empty(self):
        from steward.handlers.admin_handler import AdminViewHandler

        repo = make_repository()
        reply, ok = await invoke(AdminViewHandler, "/admin", repo)
        assert ok
        assert "нет" in reply

    async def test_shows_admin_ids(self):
        from steward.handlers.admin_handler import AdminViewHandler

        repo = make_repository()
        repo.db.admin_ids = {100, 200}
        reply, ok = await invoke(AdminViewHandler, "/admin", repo)
        assert ok
        assert "100" in reply or "200" in reply

    async def test_ignores_add_subcommand(self):
        from steward.handlers.admin_handler import AdminViewHandler

        repo = make_repository()
        _, ok = await invoke(AdminViewHandler, "/admin add 100", repo)
        assert not ok

    async def test_ignores_remove_subcommand(self):
        from steward.handlers.admin_handler import AdminViewHandler

        repo = make_repository()
        _, ok = await invoke(AdminViewHandler, "/admin remove 100", repo)
        assert not ok


class TestAdminAdd:
    async def test_adds_new_admin(self):
        from steward.handlers.admin_handler import AdminAddHandler

        repo = make_repository()
        reply, _ = await invoke(AdminAddHandler, "/admin add 99", repo)
        assert 99 in repo.db.admin_ids
        assert "99" in reply

    async def test_rejects_duplicate(self):
        from steward.handlers.admin_handler import AdminAddHandler

        repo = make_repository()
        repo.db.admin_ids = {99}
        reply, _ = await invoke(AdminAddHandler, "/admin add 99", repo)
        assert "уже" in reply
        assert len(repo.db.admin_ids) == 1


class TestAdminRemove:
    async def test_removes_admin(self):
        from steward.handlers.admin_handler import AdminRemoveHandler

        repo = make_repository()
        repo.db.admin_ids = {99}
        reply, _ = await invoke(AdminRemoveHandler, "/admin remove 99", repo)
        assert 99 not in repo.db.admin_ids
        assert "99" in reply

    async def test_nonexistent_admin(self):
        from steward.handlers.admin_handler import AdminRemoveHandler

        repo = make_repository()
        reply, _ = await invoke(AdminRemoveHandler, "/admin remove 99", repo)
        assert "не существует" in reply
        assert len(repo.db.admin_ids) == 0
