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

    async def test_migrate_adds_done_words_offset(self):
        repo = make_repository()

        migrated = repo._migrate(
            {
                "version": 16,
                "curse_participants": [
                    {
                        "user_id": 1,
                        "subscribed_at": "2026-01-01T00:00:00+00:00",
                        "last_done_at": None,
                        "source_chat_ids": [123],
                    }
                ],
            }
        )

        assert migrated["version"] >= 17
        assert migrated["curse_participants"][0]["done_words_offset"] == 0
