from tests.conftest import make_repository


class TestCurseRepositoryMigration:
    async def test_migrate_adds_curse_fields(self):
        repo = make_repository()

        migrated = repo._migrate({"version": 11, "admin_ids": []})

        # Migration is applied in sequence; reaching v12 adds curse fields,
        # subsequent steps (v12→v13, …) continue along the chain.
        assert migrated["version"] >= 12
        assert migrated["curse_words"] == []
        assert migrated["curse_punishments"] == []
        assert migrated["curse_participants"] == []
