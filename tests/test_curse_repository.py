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

    async def test_migrate_adds_curse_ignore_words(self):
        repo = make_repository()

        migrated = repo._migrate({"version": 34, "admin_ids": []})

        assert migrated["version"] >= 35
        assert migrated["curse_ignore_words"] == []

    async def test_migrate_adds_curse_debt_fields(self):
        repo = make_repository()

        migrated = repo._migrate({"version": 35, "admin_ids": []})

        assert migrated["version"] >= 36
        assert migrated["curse_punishment_debts"] == []
        assert migrated["curse_debts_backfilled"] is False

    async def test_migrate_adds_interest_percent_to_existing_punishments(self):
        repo = make_repository()

        migrated = repo._migrate(
            {
                "version": 35,
                "admin_ids": [],
                "curse_punishments": [{"id": 1, "coeff": 5, "title": "отжиманий"}],
            }
        )

        assert migrated["curse_punishments"][0]["interest_percent"] == 0.0

    async def test_migrate_adds_punishment_day_fields(self):
        repo = make_repository()

        migrated = repo._migrate(
            {
                "version": 36,
                "admin_ids": [],
                "curse_punishments": [{"id": 1, "coeff": 5, "title": "отжиманий"}],
            }
        )

        assert migrated["version"] >= 36
        assert migrated["curse_punishment_days"] == []
        assert migrated["curse_punishments"][0]["selection_weight"] == 1.0
