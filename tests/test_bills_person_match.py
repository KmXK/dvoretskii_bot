"""Tests for bills_person_match: ranked disambiguation."""
from datetime import datetime, timedelta

from steward.data.models.bill_v2 import BillPerson
from steward.data.models.user import User
from steward.helpers.bills_person_match import (
    match_name,
    rank_person_matches,
    update_chat_last_seen,
)


def _person(pid, name, telegram_id=None, aliases=None, chat_last_seen=None):
    return BillPerson(
        id=pid,
        display_name=name,
        telegram_id=telegram_id,
        aliases=aliases or [],
        chat_last_seen=chat_last_seen or {},
    )


class TestRankPersonMatches:
    def test_exact_match(self):
        persons = [_person("1", "Лёша")]
        ranked = rank_person_matches("Лёша", persons, {})
        assert len(ranked) == 1
        assert ranked[0][1] >= 1000

    def test_alias_match(self):
        persons = [_person("1", "Алексей", aliases=["Лёша", "Лёха"])]
        ranked = rank_person_matches("Лёша", persons, {})
        assert len(ranked) == 1
        assert ranked[0][1] >= 1000

    def test_no_match_returns_empty(self):
        persons = [_person("1", "Кирилл")]
        ranked = rank_person_matches("Лёша", persons, {})
        assert ranked == []

    def test_recent_chat_bonus(self):
        """Person with recent chat_last_seen ranks higher than one without."""
        recent = (datetime.now() - timedelta(days=1)).isoformat()
        old = (datetime.now() - timedelta(days=365)).isoformat()
        p_recent = _person("1", "Лёша", chat_last_seen={"100": recent})
        p_old = _person("2", "Лёша", chat_last_seen={"100": old})
        persons = [p_old, p_recent]
        ranked = rank_person_matches("Лёша", persons, {}, origin_chat_id=100)
        assert ranked[0][0].id == "1"
        assert ranked[0][1] > ranked[1][1]

    def test_shared_chat_bonus(self):
        """Person with shared chat membership gets +150."""
        caller_user = User(id=10, chat_ids=[200])
        target_user = User(id=20, chat_ids=[200])
        users_by_id = {10: caller_user, 20: target_user}
        p1 = _person("1", "Лёша", telegram_id=20)
        p2 = _person("2", "Лёша", telegram_id=30)
        ranked = rank_person_matches(
            "Лёша", [p1, p2], users_by_id,
            caller_telegram_id=10, origin_chat_id=200,
        )
        assert ranked[0][0].id == "1"


class TestMatchName:
    def test_auto_match_when_clear_winner(self):
        """When top score >= 800 and gap >= 300, auto-match."""
        persons = [_person("1", "Лёша")]
        person, candidates = match_name("Лёша", persons, {})
        assert person is not None
        assert person.id == "1"
        assert candidates == []

    def test_ambiguous_returns_candidates(self):
        """Two equally good matches → no auto-match, return candidates."""
        persons = [_person("1", "Лёша"), _person("2", "Лёша")]
        person, candidates = match_name("Лёша", persons, {})
        assert person is None
        assert len(candidates) == 2

    def test_no_match(self):
        person, candidates = match_name("Кирилл", [_person("1", "Лёша")], {})
        assert person is None
        assert candidates == []


class TestUpdateChatLastSeen:
    def test_records_iso_datetime(self):
        p = _person("1", "Лёша")
        update_chat_last_seen(p, 200)
        assert "200" in p.chat_last_seen
        # Should parse as a valid datetime
        datetime.fromisoformat(p.chat_last_seen["200"])
