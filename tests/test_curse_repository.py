from steward.data.repository import Repository
from tests.conftest import make_repository


class TestCurseRepositoryMigration:
    async def test_migrate_adds_curse_words(self):
        repo = make_repository()

        migrated = repo._migrate({"version": 11, "admin_ids": []})

        assert migrated["version"] == 12
        assert migrated["curse_words"] == []
