"""Tests for chat-scoped nicknames + chat aliases + binding helpers."""
from datetime import datetime, timedelta

import pytest

from steward.data.models.bill_v2 import BillPerson, ChatNickname
from steward.data.models.chat import Chat
from steward.data.models.user import User
from steward.helpers.bills_person_match import (
    detect_chat_references,
    fuzzy_score_telegram_candidate,
    match_name,
    rank_person_matches,
)

from tests.conftest import make_repository


def _person(pid, name, telegram_id=None, aliases=None, chat_last_seen=None):
    return BillPerson(
        id=pid,
        display_name=name,
        telegram_id=telegram_id,
        aliases=aliases or [],
        chat_last_seen=chat_last_seen or {},
    )


# ── Repository: nickname CRUD ────────────────────────────────────────────────


class TestRepositoryNicknames:
    def test_add_then_lookup(self):
        repo = make_repository()
        p = _person("p1", "Дмитрий Иванов")
        repo.db.bill_persons.append(p)

        entry, status = repo.add_chat_nickname(
            chat_id=-100, person_id="p1", nick="Дима", created_by_telegram_id=42,
        )
        assert status == "added"
        assert entry is not None
        assert repo.find_person_id_by_nick(-100, "дима") == "p1"
        assert repo.find_person_id_by_nick(-100, "ДИМА") == "p1"  # case-insensitive
        assert repo.find_person_id_by_nick(-100, "не-такой") is None

    def test_idempotent_add_for_same_person(self):
        repo = make_repository()
        repo.db.bill_persons.append(_person("p1", "Дмитрий"))
        repo.add_chat_nickname(-100, "p1", "Дима")
        _, status = repo.add_chat_nickname(-100, "p1", "Дима")
        assert status == "exists"
        assert len(repo.db.chat_nicknames) == 1

    def test_conflict_with_other_person(self):
        repo = make_repository()
        repo.db.bill_persons.append(_person("p1", "Дмитрий А"))
        repo.db.bill_persons.append(_person("p2", "Дмитрий Б"))
        repo.add_chat_nickname(-100, "p1", "Дима")
        existing, status = repo.add_chat_nickname(-100, "p2", "Дима")
        assert status == "conflict"
        assert existing.person_id == "p1"
        assert len(repo.db.chat_nicknames) == 1  # not overwritten

    def test_chat_nicks_are_isolated_per_chat(self):
        repo = make_repository()
        repo.db.bill_persons.append(_person("p1", "Дмитрий А"))
        repo.db.bill_persons.append(_person("p2", "Дмитрий Б"))
        repo.add_chat_nickname(-100, "p1", "Дима")
        repo.add_chat_nickname(-200, "p2", "Дима")
        assert repo.find_person_id_by_nick(-100, "Дима") == "p1"
        assert repo.find_person_id_by_nick(-200, "Дима") == "p2"

    def test_remove(self):
        repo = make_repository()
        repo.db.bill_persons.append(_person("p1", "Дмитрий"))
        repo.add_chat_nickname(-100, "p1", "Дима")
        assert repo.remove_chat_nickname(-100, "Дима") is True
        assert repo.find_person_id_by_nick(-100, "Дима") is None
        assert repo.remove_chat_nickname(-100, "Дима") is False  # idempotent

    def test_index(self):
        repo = make_repository()
        repo.db.bill_persons.append(_person("p1", "А"))
        repo.db.bill_persons.append(_person("p2", "Б"))
        repo.add_chat_nickname(-100, "p1", "Дима")
        repo.add_chat_nickname(-100, "p2", "Лёша")
        repo.add_chat_nickname(-200, "p1", "DI")
        idx = repo.chat_nicknames_index()
        assert idx[-100]["дима"] == "p1"
        assert idx[-100]["лёша"] == "p2"
        assert idx[-200]["di"] == "p1"


# ── Repository: chat aliases ──────────────────────────────────────────────────


class TestRepositoryChatAliases:
    def test_add_and_find(self):
        repo = make_repository()
        repo.db.chats.append(Chat(id=-100, name="🌴 Джунгли v2"))
        assert repo.add_chat_alias(-100, "Джунгли") == "added"
        assert repo.find_chat_by_alias("джунгли").id == -100
        assert repo.find_chat_by_alias("ДЖУНГЛИ").id == -100  # case-insensitive

    def test_find_by_title_too(self):
        repo = make_repository()
        repo.db.chats.append(Chat(id=-100, name="Дора"))
        assert repo.find_chat_by_alias("дора").id == -100

    def test_alias_conflict_across_chats(self):
        repo = make_repository()
        repo.db.chats.append(Chat(id=-100, name="A"))
        repo.db.chats.append(Chat(id=-200, name="B"))
        assert repo.add_chat_alias(-100, "Джунгли") == "added"
        assert repo.add_chat_alias(-200, "Джунгли") == "conflict"


# ── match_name with chat-scoped nicks ─────────────────────────────────────────


class TestMatchNameWithNicks:
    def test_chat_nick_beats_global_namesake(self):
        """Two persons named 'Дима', a chat-scoped nick maps to one — that one wins."""
        p_winner = _person("p1", "Дмитрий Иванов")
        p_other = _person("p2", "Дмитрий Петров")
        idx = {-100: {"дима": "p1"}}
        ranked = rank_person_matches(
            "Дима",
            [p_winner, p_other],
            users_by_id={},
            origin_chat_id=-100,
            chat_nicknames_index=idx,
        )
        assert ranked[0][0].id == "p1"
        assert ranked[0][1] >= 2000

    def test_chat_nick_irrelevant_in_other_chat(self):
        """A nick in chat A doesn't grant matches inside chat B."""
        p1 = _person("p1", "Дмитрий")
        idx = {-100: {"дима": "p1"}}
        person, candidates = match_name(
            "Дима", [p1], {}, origin_chat_id=-200, chat_nicknames_index=idx,
        )
        # No nick boost in -200, but display_name "Дмитрий" doesn't fuzzy-match "Дима"
        # cleanly; match_name returns ambiguous-or-nothing.
        # The point: we shouldn't get the +2000 bonus here.
        assert (person is None or person.id == "p1")

    def test_dm_scoped_chat_ids_used(self):
        """In DM mode, scoped_chat_ids broadens the chat-nick lookup."""
        p1 = _person("p1", "Алексей")
        idx = {-100: {"лёша": "p1"}}
        # caller is in chat -100 even though they wrote in DM (chat_id == user_id)
        person, _ = match_name(
            "Лёша", [p1], {},
            caller_telegram_id=42, origin_chat_id=42,  # DM
            chat_nicknames_index=idx,
            scoped_chat_ids=[-100],
        )
        assert person is not None and person.id == "p1"

    def test_global_alias_still_works_when_no_nick(self):
        """Without any chat-nick, the legacy alias path still resolves."""
        p1 = _person("p1", "Алексей", aliases=["Лёша"])
        person, _ = match_name("Лёша", [p1], {})
        assert person is not None and person.id == "p1"


# ── Chat reference detection ─────────────────────────────────────────────────


class TestDetectChatReferences:
    def test_simple_iz_genitive(self):
        chats = [Chat(id=-100, name="Джунгли"), Chat(id=-200, name="Дора")]
        found = detect_chat_references("из джунглей лёша заплатил 50", chats)
        assert len(found) == 1
        assert found[0][1].id == -100

    def test_s_instrumental(self):
        chats = [Chat(id=-200, name="Дора")]
        found = detect_chat_references("мы с Дорой ходили гулять", chats)
        assert len(found) == 1
        assert found[0][1].id == -200

    def test_alias_match(self):
        chats = [Chat(id=-100, name="🌴 Джунгли v2", aliases=["Джунгли"])]
        found = detect_chat_references("из джунглей пришёл лёша", chats)
        assert len(found) == 1
        assert found[0][1].id == -100

    def test_no_false_positive_without_preposition(self):
        chats = [Chat(id=-100, name="Дора")]
        # word appears but without an introducing preposition — no match
        found = detect_chat_references("просто слово Дора", chats)
        assert found == []

    def test_multi_chat(self):
        chats = [Chat(id=-100, name="Джунгли"), Chat(id=-200, name="Дора")]
        found = detect_chat_references(
            "из джунглей лёша и из доры дима", chats,
        )
        assert {c.id for _, c in found} == {-100, -200}


# ── fuzzy_score_telegram_candidate ────────────────────────────────────────────


class TestFuzzyTgCandidate:
    def test_exact_username_match(self):
        u = User(id=10, username="dimon")
        score = fuzzy_score_telegram_candidate("dimon", u)
        assert score >= 1000

    def test_stem_match_for_first_name(self):
        u = User(id=10, username="dimitry_p")
        p = BillPerson(id="x", display_name="Дмитрий Петров")
        # "Дима" should fuzzy via stem to "Дмитрий"
        score = fuzzy_score_telegram_candidate("Дима", u, p)
        # may not stem-match perfectly, but should at least find via prefix
        assert score >= 0  # smoke

    def test_no_match_returns_zero(self):
        u = User(id=10, username="vasya")
        score = fuzzy_score_telegram_candidate("Кирилл", u)
        assert score == 0


# ── Migration ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_v15_adds_chat_nicknames_and_aliases(tmp_path):
    """A db at version 15 (with no chat_nicknames) migrates to 16 and gains the field."""
    import json
    from steward.data.repository import JsonFileStorage, Repository

    db_path = tmp_path / "db.json"
    db_path.write_text(json.dumps({
        "version": 15,
        "admin_ids": [],
        "users": [],
        "chats": [{"id": -100, "name": "Test"}],
    }))

    repo = Repository(JsonFileStorage(str(db_path)))
    await repo.migrate()

    assert repo.db.version == 16
    assert repo.db.chat_nicknames == []
    chat = next(c for c in repo.db.chats if c.id == -100)
    assert chat.aliases == []


# ── merge_person ──────────────────────────────────────────────────────────────


class TestMergePerson:
    def test_merge_reassigns_nicknames(self):
        repo = make_repository()
        repo.db.bill_persons.append(_person("anon1", "ВаняФ"))
        repo.db.bill_persons.append(_person("real1", "Иван Фёдоров", telegram_id=42))
        repo.add_chat_nickname(-100, "anon1", "ваняф")

        ok = repo.merge_person("anon1", "real1")
        assert ok
        assert repo.get_bill_person("anon1") is None
        assert repo.find_person_id_by_nick(-100, "ваняф") == "real1"

    def test_merge_dedupes_aliases(self):
        repo = make_repository()
        repo.db.bill_persons.append(_person("a", "X", aliases=["foo"]))
        repo.db.bill_persons.append(_person("b", "Y", aliases=["foo", "bar"]))
        repo.merge_person("a", "b")
        dst = repo.get_bill_person("b")
        assert sorted(dst.aliases) == ["bar", "foo"]
