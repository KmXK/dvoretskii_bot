"""Tests for AdminFeature: view, add, remove."""
import pytest

from steward.data.models.user import User
from tests.conftest import invoke, make_repository


class TestAdminView:
    async def test_empty(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        reply, ok = await invoke(AdminFeature, "/admin", repo)
        assert ok
        assert "нет" in reply

    async def test_shows_admin_ids(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        repo.db.admin_ids = {100, 200}
        reply, ok = await invoke(AdminFeature, "/admin", repo)
        assert ok
        assert "100" in reply or "200" in reply


class TestAdminAdd:
    async def test_adds_new_admin(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        reply, _ = await invoke(AdminFeature, "/admin add 99", repo)
        assert 99 in repo.db.admin_ids
        assert "99" in reply

    async def test_rejects_duplicate(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        repo.db.admin_ids = {99}
        reply, _ = await invoke(AdminFeature, "/admin add 99", repo)
        assert "уже" in reply
        assert len(repo.db.admin_ids) == 1


class TestAdminRemove:
    async def test_removes_admin(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        repo.db.admin_ids = {99}
        reply, _ = await invoke(AdminFeature, "/admin remove 99", repo)
        assert 99 not in repo.db.admin_ids
        assert "99" in reply

    async def test_nonexistent_admin(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        reply, _ = await invoke(AdminFeature, "/admin remove 99", repo)
        assert "не существует" in reply
        assert len(repo.db.admin_ids) == 0


class TestAdminUsername:
    async def test_add_by_username(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        repo.db.users.append(User(id=42, username="vasya"))
        reply, _ = await invoke(AdminFeature, "/admin add @vasya", repo)
        assert 42 in repo.db.admin_ids
        assert "@vasya" in reply

    async def test_add_unknown_username(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        reply, _ = await invoke(AdminFeature, "/admin add @unknown", repo)
        assert len(repo.db.admin_ids) == 0
        assert "не найден" in reply

    async def test_view_shows_username(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        repo.db.admin_ids = {42}
        repo.db.users.append(User(id=42, username="vasya"))
        reply, _ = await invoke(AdminFeature, "/admin", repo)
        assert "@vasya" in reply
        assert "42" not in reply

    async def test_view_falls_back_to_id(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        repo.db.admin_ids = {99}
        reply, _ = await invoke(AdminFeature, "/admin", repo)
        assert "99" in reply

    async def test_remove_by_username(self):
        from steward.features.admin import AdminFeature

        repo = make_repository()
        repo.db.admin_ids = {42}
        repo.db.users.append(User(id=42, username="vasya"))
        reply, _ = await invoke(AdminFeature, "/admin remove @vasya", repo)
        assert 42 not in repo.db.admin_ids
        assert "@vasya" in reply
