"""Тесты привязки устройств (часов): коды, токены, отзыв, миграция."""
import pytest

from steward.api import watch_pairing as wp
from steward.api.watch_pairing import (
    CODE_LENGTH,
    CODE_TTL_SECONDS,
    claim_code,
    find_device_by_token,
    hash_token,
    normalize_code,
    revoke_device,
    start_pairing,
)
import json

from steward.data.models.db import Database, parse_from_dict, serialize_to_dict
from steward.data.repository import JsonEncoder
from tests.conftest import make_repository


@pytest.fixture(autouse=True)
def _clear_pending():
    wp._pending_codes.clear()
    yield
    wp._pending_codes.clear()


# ── коды ────────────────────────────────────────────────────────────────────

def test_start_pairing_returns_code_and_ttl():
    code, ttl = start_pairing(111)
    assert len(code) == CODE_LENGTH
    assert ttl == CODE_TTL_SECONDS
    assert all(ch in wp._CODE_ALPHABET for ch in code)


def test_start_pairing_invalidates_previous_code_for_same_user():
    first, _ = start_pairing(111)
    second, _ = start_pairing(111)
    assert first != second
    assert first not in wp._pending_codes
    assert second in wp._pending_codes


def test_normalize_code_strips_and_uppercases():
    code, _ = start_pairing(111)
    spaced = " ".join(code.lower())  # нижний регистр + пробелы
    assert normalize_code(spaced) == code


# ── claim ─────────────────────────────────────────────────────────────────────

def test_claim_code_creates_device_and_returns_token():
    repo = make_repository()
    code, _ = start_pairing(777)
    result = claim_code(repo, code, "Galaxy Watch")
    assert result is not None
    device, token = result
    assert device.user_id == 777
    assert device.name == "Galaxy Watch"
    assert token
    assert device.token_hash == hash_token(token)
    assert repo.db.paired_devices == [device]


def test_claim_code_is_one_time():
    repo = make_repository()
    code, _ = start_pairing(777)
    assert claim_code(repo, code, "Watch") is not None
    # повторный обмен того же кода — отказ
    assert claim_code(repo, code, "Watch") is None
    assert len(repo.db.paired_devices) == 1


def test_claim_code_rejects_unknown():
    repo = make_repository()
    assert claim_code(repo, "ZZZZZZZZ", "Watch") is None
    assert repo.db.paired_devices == []


def test_claim_code_rejects_expired():
    repo = make_repository()
    code, _ = start_pairing(777, now=1000.0)
    # пробуем заклеймить уже после истечения TTL
    assert claim_code(repo, code, "Watch", now=1000.0 + CODE_TTL_SECONDS + 1) is None


def test_claim_code_blank_name_defaults():
    repo = make_repository()
    code, _ = start_pairing(1)
    device, _ = claim_code(repo, code, "   ")
    assert device.name == "Устройство"


def test_claim_assigns_incrementing_ids():
    repo = make_repository()
    c1, _ = start_pairing(1)
    d1, _ = claim_code(repo, c1, "A")
    c2, _ = start_pairing(2)
    d2, _ = claim_code(repo, c2, "B")
    assert d1.id == 1
    assert d2.id == 2


# ── токены ──────────────────────────────────────────────────────────────────

def test_find_device_by_token_roundtrip():
    repo = make_repository()
    code, _ = start_pairing(42)
    device, token = claim_code(repo, code, "Watch")
    found = find_device_by_token(repo, token)
    assert found is device


def test_find_device_by_token_wrong_token():
    repo = make_repository()
    code, _ = start_pairing(42)
    claim_code(repo, code, "Watch")
    assert find_device_by_token(repo, "nope") is None
    assert find_device_by_token(repo, "") is None


# ── отзыв ─────────────────────────────────────────────────────────────────────

def test_revoke_device_only_own():
    repo = make_repository()
    c1, _ = start_pairing(1)
    d1, _ = claim_code(repo, c1, "A")
    c2, _ = start_pairing(2)
    d2, _ = claim_code(repo, c2, "B")
    # чужой юзер не может отозвать
    assert revoke_device(repo, 999, d1.id) is False
    assert len(repo.db.paired_devices) == 2
    # владелец может
    assert revoke_device(repo, 1, d1.id) is True
    assert [d.id for d in repo.db.paired_devices] == [d2.id]


# ── персистентность / миграция ────────────────────────────────────────────────

def test_paired_device_survives_serialization():
    repo = make_repository()
    code, _ = start_pairing(5)
    device, token = claim_code(repo, code, "Watch")
    # Реальный поток сериализации: dataclass → JSON (JsonEncoder) → dict → dataclass.
    data = json.loads(json.dumps(serialize_to_dict(repo.db), cls=JsonEncoder))
    restored = parse_from_dict(data)
    assert len(restored.paired_devices) == 1
    rd = restored.paired_devices[0]
    assert rd.user_id == 5
    assert find_device_by_token_in(restored, token) is rd


def find_device_by_token_in(db, token):
    candidate = hash_token(token)
    return next((d for d in db.paired_devices if d.token_hash == candidate), None)


def test_default_database_has_paired_devices():
    assert Database().paired_devices == []
    assert Database().version == 37


def test_migration_v36_to_37_adds_paired_devices():
    repo = make_repository()
    migrated = repo._migrate({"version": 36, "admin_ids": []})
    assert migrated["version"] == 37
    assert migrated["paired_devices"] == []
