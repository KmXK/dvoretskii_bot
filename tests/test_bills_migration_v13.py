"""Tests for db migration that initializes bill_v2 collections (now v13 → v14)."""
import os
import tempfile

import pytest

from steward.data.repository import JsonFileStorage, Repository


@pytest.mark.asyncio
async def test_migration_from_v11_adds_new_fields():
    """Loading a v11-shaped db.json should not lose data and should reach the latest version with bill_v2 defaults."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        # Minimal v11 snapshot
        import json
        json.dump({
            "version": 11,
            "admin_ids": [],
            "users": [],
        }, f)
        db_path = f.name

    try:
        repo = Repository(JsonFileStorage(db_path))
        await repo.migrate()
        # Migration should have happened all the way to current
        assert repo.db.version == 16
        # New fields should be initialized to defaults
        assert repo.db.bill_persons == []
        assert repo.db.bills_v2 == []
        assert repo.db.bill_payments_v2 == []
        assert repo.db.bill_item_suggestions == []
        assert repo.db.bill_draft_edits == []
        assert repo.db.chat_nicknames == []
    finally:
        os.unlink(db_path)
        # Also clean backup
        bak = db_path + ".bak.v13"
        if os.path.exists(bak):
            os.unlink(bak)


@pytest.mark.asyncio
async def test_migration_creates_backup():
    """Migration must back up db.json before applying."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        import json
        json.dump({"version": 11, "admin_ids": [], "users": []}, f)
        db_path = f.name

    try:
        repo = Repository(JsonFileStorage(db_path))
        await repo.migrate()
        bak = db_path + ".bak.v13"
        assert os.path.exists(bak), "v11 backup should exist after migration"
    finally:
        for p in [db_path, db_path + ".bak.v13"]:
            if os.path.exists(p):
                os.unlink(p)
