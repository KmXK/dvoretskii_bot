"""Tests for AI response parser — both canonical use cases."""
from steward.features.bills.parse import (
    norm_name_key as _norm_name_key,
    parse_ai_response as _parse_ai_response,
    rows_to_transactions as _rows_to_transactions,
)
from steward.data.models.bill_v2 import UNKNOWN_PERSON_ID


def _nmap(raw_map: dict[str, str]) -> dict[str, str]:
    """Build a normalized-key name→id map from a raw dict."""
    return {_norm_name_key(k): v for k, v in raw_map.items()}


class TestParseAIResponse:
    def test_meta_currency(self):
        text = """[META]
currency: USD

[ОБЩЕЕ]

[ДАННЫЕ]
"""
        currency, rows, persons, _q = _parse_ai_response(text)
        assert currency == "USD"
        assert rows == []
        assert persons == []

    def test_default_currency_byn(self):
        text = """[META]

[ОБЩЕЕ]

[ДАННЫЕ]
"""
        currency, _, _, _ = _parse_ai_response(text)
        assert currency == "BYN"

    def test_simple_row(self):
        text = """[META]
currency: BYN

[ОБЩЕЕ]
Чай | 5.00 | 1 | Кирилл | Паша | Текст |

[ДАННЫЕ]
"""
        currency, rows, _, _ = _parse_ai_response(text)
        assert len(rows) == 1
        assert rows[0]["name"] == "Чай"
        assert rows[0]["price_minor"] == 500
        assert rows[0]["quantity"] == 1
        assert rows[0]["debtors_raw"] == "Кирилл"
        assert rows[0]["creditor_raw"] == "Паша"
        assert rows[0]["group_id"] == ""

    def test_ice_cream_per_person(self):
        """Use case 1: 'Купил себе и Лёше мороженое по 3 рубля' → 2 separate rows."""
        text = """[META]
currency: BYN

[ОБЩЕЕ]
Мороженое | 3 | 1 | Кирилл | Кирилл | Голосовое |
Мороженое | 3 | 1 | Лёша | Кирилл | Голосовое |

[ДАННЫЕ]
"""
        _, rows, _, _ = _parse_ai_response(text)
        assert len(rows) == 2
        assert rows[0]["price_minor"] == 300
        assert rows[1]["debtors_raw"] == "Лёша"

    def test_hookah_multi_assignment(self):
        """Use case 2: 3 hookahs with GroupId."""
        text = """[META]
currency: BYN

[ОБЩЕЕ]
Кальян | 20 | 2 | Дима, Егор | Паша | Голосовое | G1
Кальян | 20 | 1 | Дима, Егор, Кирилл | Паша | Голосовое | G1

[ДАННЫЕ]
"""
        _, rows, _, _ = _parse_ai_response(text)
        assert len(rows) == 2
        assert rows[0]["group_id"] == "G1"
        assert rows[1]["group_id"] == "G1"
        assert rows[0]["quantity"] == 2
        assert rows[1]["quantity"] == 1

    def test_unknown_debtor(self):
        text = """[META]

[ОБЩЕЕ]
Salt | 1 | 1 | - | - | Фото |

[ДАННЫЕ]
"""
        _, rows, _, _ = _parse_ai_response(text)
        assert rows[0]["debtors_raw"] == "-"
        assert rows[0]["creditor_raw"] == "-"

    def test_questions_with_options(self):
        text = """[META]
currency: BYN

[ОБЩЕЕ]

[ДАННЫЕ]

[ВОПРОСЫ]
Сколько ты оставил на чай? | 5 | 10 | 20 | Другое
"""
        _, _, _, qs = _parse_ai_response(text)
        assert len(qs) == 1
        assert qs[0]["text"] == "Сколько ты оставил на чай?"
        assert qs[0]["options"] == ["5", "10", "20", "Другое"]

    def test_questions_appends_drugoe(self):
        text = """[ВОПРОСЫ]
Делили на двоих или на троих? | 2 | 3
"""
        _, _, _, qs = _parse_ai_response(text)
        assert qs[0]["options"][-1] == "Другое"

    def test_skips_header_echo(self):
        """AI sometimes echoes the header line as a data row — must be skipped."""
        text = """[META]
currency: BYN

[ОБЩЕЕ]
Наименование | Цена_за_ед | Кол-во | Должник(и) | Кредитор | Источник | GroupId
Аттракционы | 21 | 1 | Кирилл | Лёша | Текст |

[ДАННЫЕ]
"""
        _, rows, _, _ = _parse_ai_response(text)
        assert len(rows) == 1
        assert rows[0]["name"] == "Аттракционы"

    def test_new_persons(self):
        text = """[META]

[ОБЩЕЕ]

[ДАННЫЕ]
Новый | где-то
Старый |
"""
        _, _, persons, _ = _parse_ai_response(text)
        assert "Новый" in persons
        assert "Старый" in persons


class TestRowsToTransactions:
    def test_ice_cream_canonical(self):
        """Canonical: 2 separate transactions, qty=1 each."""
        rows = [
            {"name": "Мороженое", "price_minor": 300, "quantity": 1,
             "debtors_raw": "Кирилл", "creditor_raw": "Кирилл", "source": "voice", "group_id": ""},
            {"name": "Мороженое", "price_minor": 300, "quantity": 1,
             "debtors_raw": "Лёша", "creditor_raw": "Кирилл", "source": "voice", "group_id": ""},
        ]
        name_to_id = _nmap({"Кирилл": "kirill_id", "Лёша": "lesha_id"})
        txs = _rows_to_transactions(rows, name_to_id)
        assert len(txs) == 2
        assert txs[0].creditor == "kirill_id"
        assert txs[0].assignments[0].debtors == ["kirill_id"]
        assert txs[1].assignments[0].debtors == ["lesha_id"]

    def test_hookah_canonical(self):
        """Canonical: 1 transaction with 2 assignments, total quantity=3."""
        rows = [
            {"name": "Кальян", "price_minor": 2000, "quantity": 2,
             "debtors_raw": "Дима, Егор", "creditor_raw": "Паша", "source": "voice", "group_id": "G1"},
            {"name": "Кальян", "price_minor": 2000, "quantity": 1,
             "debtors_raw": "Дима, Егор, Кирилл", "creditor_raw": "Паша", "source": "voice", "group_id": "G1"},
        ]
        name_to_id = _nmap({
            "Дима": "dima_id", "Егор": "egor_id",
            "Паша": "pasha_id", "Кирилл": "kirill_id",
        })
        txs = _rows_to_transactions(rows, name_to_id)
        assert len(txs) == 1
        tx = txs[0]
        assert tx.item_name == "Кальян"
        assert tx.unit_price_minor == 2000
        assert tx.quantity == 3
        assert tx.creditor == "pasha_id"
        assert len(tx.assignments) == 2
        assert tx.assignments[0].unit_count == 2
        assert tx.assignments[0].debtors == ["dima_id", "egor_id"]
        assert tx.assignments[1].unit_count == 1
        assert tx.assignments[1].debtors == ["dima_id", "egor_id", "kirill_id"]

    def test_norm_key_case_insensitive_but_preserves_yo(self):
        """Лёша and Леша stay distinct; ЛЁША == лёша."""
        assert _norm_name_key(" Лёша ") == _norm_name_key("ЛЁША")
        assert _norm_name_key("Лёша") != _norm_name_key("Леша")

    def test_rows_resolve_through_normalized_keys(self):
        rows = [
            {"name": "X", "price_minor": 100, "quantity": 1,
             "debtors_raw": " ЛЁША ", "creditor_raw": "кирилл", "source": "text", "group_id": ""},
        ]
        name_to_id = _nmap({"Лёша": "lesha_id", "Кирилл": "kirill_id"})
        txs = _rows_to_transactions(rows, name_to_id)
        assert txs[0].creditor == "kirill_id"
        assert txs[0].assignments[0].debtors == ["lesha_id"]

    def test_unresolved_creditor_becomes_unknown(self):
        rows = [
            {"name": "X", "price_minor": 100, "quantity": 1,
             "debtors_raw": "-", "creditor_raw": "-", "source": "text", "group_id": ""},
        ]
        txs = _rows_to_transactions(rows, {})
        assert txs[0].creditor == UNKNOWN_PERSON_ID
        assert txs[0].assignments[0].debtors == []
        assert txs[0].incomplete is True
