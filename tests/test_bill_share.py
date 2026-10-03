import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image, ImageDraw

from steward.api import server
from steward.data.models.bill_v2 import (
    BillItemAssignment,
    BillPerson,
    BillTransaction,
    BillV2,
    UNKNOWN_PERSON_ID,
)
from steward.helpers.bill_image import render_bill_people_png
from steward.helpers.bill_share import build_bill_share
from steward.helpers.bills_money import compute_bill_debts
from tests.conftest import make_repository


def make_bill(*transactions):
    return BillV2(
        id=7,
        name="Ужин",
        author_person_id="kirill",
        participants=["kirill", "dima"],
        transactions=list(transactions),
    )


def make_transaction(price=1001, debtors=None, denominator=1, quantity=1, unit_count=1):
    return BillTransaction(
        id="pizza",
        item_name="Пицца",
        creditor="kirill",
        unit_price_minor=price,
        quantity=quantity,
        assignments=[
            BillItemAssignment(
                unit_count=unit_count,
                denominator=denominator,
                debtors=["kirill", "dima"] if debtors is None else debtors,
            ),
        ],
    )


NAMES = {"kirill": "Кирилл", "dima": "Дима"}


def test_share_lists_person_totals_items_portions_and_unit_prices():
    bill = make_bill(make_transaction())

    share = build_bill_share(bill, NAMES)

    assert share["summary"] == "2 участника · итого 10.01 р"
    assert share["groups"] == [
        {
            "name": "Дима",
            "total": "5.01 р",
            "items": [{"label": "Пицца", "detail": "1/2 × 10.01 р", "amount": "5.01 р"}],
        },
        {
            "name": "Кирилл",
            "total": "5 р",
            "items": [{"label": "Пицца", "detail": "1/2 × 10.01 р", "amount": "5 р"}],
        },
    ]
    assert "Дима — 5.01 р\n• Пицца · 1/2 × 10.01 р = 5.01 р" in share["caption"]


def test_fractional_share_matches_debt_rounding_and_keeps_zero_participants():
    tx = make_transaction(price=1001, debtors=["dima"], denominator=4, unit_count=3)

    share = build_bill_share(make_bill(tx), NAMES)
    debts = compute_bill_debts([tx])

    assert debts["dima"]["kirill"] == 751
    assert share["groups"][0]["total"] == "7.51 р"
    assert share["groups"][0]["items"][0]["detail"] == "3/4 × 10.01 р"
    assert share["groups"][1]["total"] == "0 р"
    assert share["groups"][2]["name"] == "Не распределено"
    assert share["groups"][2]["total"] == "2.50 р"


def test_unknown_and_empty_assignments_stay_in_full_bill_total():
    bill = make_bill(
        make_transaction(price=900, debtors=["kirill", "dima", UNKNOWN_PERSON_ID]),
        make_transaction(price=200, debtors=[]),
    )

    share = build_bill_share(bill, NAMES)

    assert share["summary"] == "2 участника · итого 11 р"
    assert share["groups"][-1]["name"] == "Не распределено"
    assert share["groups"][-1]["total"] == "5 р"
    assert [item["amount"] for item in share["groups"][-1]["items"]] == ["3 р", "2 р"]


def test_rounding_difference_reconciles_groups_without_changing_debts():
    bill = make_bill(make_transaction(price=100, debtors=["dima"], denominator=3))
    bill.transactions[0].assignments *= 3

    share = build_bill_share(bill, NAMES)

    assert share["groups"][0]["total"] == "0.99 р"
    assert share["groups"][-1] == {
        "name": "Разница округления",
        "total": "0.01 р",
        "items": [],
    }
    assert share["summary"] == "2 участника · итого 1 р"


def test_long_caption_keeps_summary_and_all_items_in_image_groups():
    bill = make_bill(*(make_transaction() for _ in range(30)))
    bill.name = "🧾" * 1000

    share = build_bill_share(bill, NAMES)

    assert len(share["caption"].encode("utf-16-le")) // 2 <= 1024
    assert share["summary"] in share["caption"]
    assert "на картинке" in share["caption"]
    assert len(share["groups"][0]["items"]) == 30
    assert len(share["groups"][1]["items"]) == 30


def test_share_supports_empty_bills_and_currency():
    bill = make_bill()
    bill.currency = "USD"

    share = build_bill_share(bill, NAMES)

    assert share["summary"] == "2 участника · итого $0"
    assert all(group["total"] == "$0" for group in share["groups"])


def test_image_contains_totals_prices_and_wraps_full_item_names(monkeypatch):
    texts = []
    original = ImageDraw.ImageDraw.text

    def record_text(draw, xy, text, *args, **kwargs):
        texts.append(text)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    tx = make_transaction()
    tx.item_name = "Очень длинное название вкусной пиццы " * 5
    share = build_bill_share(make_bill(tx), NAMES)

    raw = render_bill_people_png("Ужин", share["groups"], summary=share["summary"])

    image = Image.open(BytesIO(raw))
    assert image.format == "PNG"
    assert image.width == 880
    assert image.height > 700
    assert share["summary"] in texts
    assert "5.01 р" in texts
    assert "1/2 × 10.01 р" in texts
    assert " ".join(texts).count("пиццы") == 10


def make_share_request(monkeypatch, user_id=2, closed=False):
    repository = make_repository()
    bill = make_bill(make_transaction())
    bill.closed = closed
    repository.db.bills_v2 = [bill]
    repository.db.bill_persons = [
        BillPerson(id="kirill", display_name="Кирилл", telegram_id=1),
        BillPerson(id="dima", display_name="Дима", telegram_id=2),
    ]
    sent = MagicMock(message_id=99, photo=[MagicMock(file_id="bill-photo")])
    bot = MagicMock()
    bot.send_photo = AsyncMock(return_value=sent)
    bot.delete_message = AsyncMock()
    bot.save_prepared_inline_message = AsyncMock(return_value=MagicMock(id="prepared-bill"))
    request = MagicMock()
    request.app = {"repository": repository, "bot": bot}
    request.match_info = {"id": "7"}
    monkeypatch.setattr(server, "_get_tg_user_from_request", lambda _: {"id": user_id} if user_id else None)
    return request, bot


@pytest.mark.parametrize("closed", [False, True])
async def test_participant_can_share_open_or_closed_bill(monkeypatch, closed):
    request, bot = make_share_request(monkeypatch, closed=closed)

    response = await server.handle_bills_share_image(request)

    assert response.status == 200
    assert json.loads(response.text) == {"prepared_message_id": "prepared-bill"}
    bot.send_photo.assert_awaited_once()
    assert bot.send_photo.call_args.kwargs["chat_id"] == 2
    bot.delete_message.assert_awaited_once_with(chat_id=2, message_id=99)
    result = bot.save_prepared_inline_message.call_args.args[1]
    assert result.photo_file_id == "bill-photo"
    assert "Дима — 5.01 р" in result.caption
    assert "Пицца · 1/2 × 10.01 р = 5.01 р" in result.caption
    assert bot.save_prepared_inline_message.call_args.kwargs["allow_user_chats"] is True


@pytest.mark.parametrize("user_id,status", [(None, 401), (99, 403)])
async def test_share_rejects_unauthenticated_or_unrelated_user(monkeypatch, user_id, status):
    request, bot = make_share_request(monkeypatch, user_id=user_id)

    response = await server.handle_bills_share_image(request)

    assert response.status == status
    bot.send_photo.assert_not_awaited()
    bot.save_prepared_inline_message.assert_not_awaited()


async def test_large_bill_shares_as_file_without_losing_items(monkeypatch):
    request, bot = make_share_request(monkeypatch)
    bill = request.app["repository"].db.bills_v2[0]
    bill.transactions = [make_transaction() for _ in range(80)]
    sent = MagicMock(message_id=99, document=MagicMock(file_id="bill-document"))
    bot.send_document = AsyncMock(return_value=sent)

    response = await server.handle_bills_share_image(request)

    assert response.status == 200
    bot.send_photo.assert_not_awaited()
    bot.send_document.assert_awaited_once()
    result = bot.save_prepared_inline_message.call_args.args[1]
    assert result.document_file_id == "bill-document"
    assert "итого 800.80 р" in result.caption
    assert "на картинке" in result.caption
