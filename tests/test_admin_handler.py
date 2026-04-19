"""Tests for AdminFeature: view, add, remove."""
import pytest

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
