import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from steward.api import server
from steward.data.models.bill_v2 import (
    BillItemAssignment,
    BillPaymentV2,
    BillPerson,
    BillTransaction,
    BillV2,
    PaymentStatus,
)
from steward.features.bills import BillsFeature
from steward.features.bills import payments as payment_service
from steward.helpers.bills_money import compute_bill_balances
from tests.conftest import invoke, make_repository


DEBTOR_TELEGRAM_ID = 101
CREDITOR_TELEGRAM_ID = 202


def add_people(repository, creditor_telegram_id=CREDITOR_TELEGRAM_ID):
    debtor = BillPerson(
        id="debtor",
        display_name="Дима",
        telegram_id=DEBTOR_TELEGRAM_ID,
        telegram_username="dima",
    )
    creditor = BillPerson(
        id="creditor",
        display_name="Кирилл",
        telegram_id=creditor_telegram_id,
        telegram_username="kirill",
        description="СБП +375 29 123-45-67",
    )
    repository.db.bill_persons.extend([debtor, creditor])
    return debtor, creditor


def add_bill(
    repository,
    bill_id: int,
    amount_minor: int,
    *,
    currency: str = "BYN",
    created_at: datetime | None = None,
    distribution_status: str = "final",
) -> BillV2:
    bill = BillV2(
        id=bill_id,
        name=f"Счёт {bill_id}",
        author_person_id="creditor",
        participants=["debtor", "creditor"],
        transactions=[
            BillTransaction(
                id=f"tx-{bill_id}",
                item_name="Ужин",
                creditor="creditor",
                unit_price_minor=amount_minor,
                assignments=[
                    BillItemAssignment(
                        unit_count=1,
                        debtors=["debtor"],
                    )
                ],
            )
        ],
        currency=currency,
        created_at=created_at or datetime(2026, 9, 1),
        distribution_status=distribution_status,
    )
    repository.db.bills_v2.append(bill)
    return bill


def make_request(repository, data=None, match_info=None, bot=None):
    request = MagicMock()
    request.app = {
        "repository": repository,
        "bot": bot or MagicMock(),
    }
    request.match_info = match_info or {}
    request.json = AsyncMock(return_value=data or {})
    return request


def response_json(response):
    return json.loads(response.text)


def test_settle_partial_payment_across_bills_fifo():
    repository = make_repository()
    add_people(repository)
    first = add_bill(repository, 1, 1000, created_at=datetime(2026, 9, 1))
    second = add_bill(repository, 2, 2000, created_at=datetime(2026, 9, 2))
    payment = BillPaymentV2(
        id="payment",
        debtor="debtor",
        creditor="creditor",
        amount_minor=1500,
        currency="BYN",
        status=PaymentStatus.CONFIRMED,
    )
    repository.db.bill_payments_v2.append(payment)

    settlement = payment_service.settle_payment(repository, payment)

    assert settlement.allocations == [(1, 1000), (2, 500)]
    assert settlement.residual_minor == 0
    assert [(item.bill_ids, item.amount_minor) for item in settlement.payments] == [
        ([1], 1000),
        ([2], 500),
    ]
    assert payment not in repository.db.bill_payments_v2
    assert first.closed is True
    assert second.closed is False
    balances, _ = compute_bill_balances(
        repository.db.bills_v2,
        repository.db.bill_payments_v2,
    )
    assert balances[2]["debtor"]["creditor"] == 1500


def test_settle_keeps_overpayment_and_currency_isolated():
    repository = make_repository()
    add_people(repository)
    byn_bill = add_bill(repository, 1, 1000, currency="BYN")
    usd_bill = add_bill(repository, 2, 1000, currency="USD")
    payment = BillPaymentV2(
        id="payment",
        debtor="debtor",
        creditor="creditor",
        amount_minor=1500,
        currency="BYN",
        status=PaymentStatus.CONFIRMED,
    )
    repository.db.bill_payments_v2.append(payment)

    settlement = payment_service.settle_payment(repository, payment)

    assert settlement.allocations == [(1, 1000)]
    assert settlement.residual_minor == 500
    assert byn_bill.closed is True
    assert usd_bill.closed is False
    balances, credits = compute_bill_balances(
        repository.db.bills_v2,
        repository.db.bill_payments_v2,
    )
    assert balances[2]["debtor"]["creditor"] == 1000
    assert credits[("debtor", "creditor", "BYN")] == 500


def test_settle_payment_respects_selected_bill():
    repository = make_repository()
    add_people(repository)
    add_bill(repository, 1, 1000, created_at=datetime(2026, 9, 1))
    add_bill(repository, 2, 1000, created_at=datetime(2026, 9, 2))
    payment = BillPaymentV2(
        id="payment",
        debtor="debtor",
        creditor="creditor",
        amount_minor=400,
        currency="BYN",
        status=PaymentStatus.CONFIRMED,
        bill_ids=[2],
    )
    repository.db.bill_payments_v2.append(payment)

    settlement = payment_service.settle_payment(repository, payment)

    assert settlement.allocations == [(2, 400)]
    balances, _ = compute_bill_balances(
        repository.db.bills_v2,
        repository.db.bill_payments_v2,
    )
    assert balances[1]["debtor"]["creditor"] == 1000
    assert balances[2]["debtor"]["creditor"] == 600


def test_find_debt_bill_ids_skips_drafts_and_other_currencies():
    repository = make_repository()
    add_people(repository)
    add_bill(repository, 1, 1000, currency="BYN")
    add_bill(repository, 2, 1000, currency="USD")
    add_bill(repository, 3, 1000, currency="BYN", distribution_status="draft")
    hidden = add_bill(repository, 4, 1000, currency="BYN")
    hidden.participants = ["creditor"]

    assert payment_service.find_debt_bill_ids(
        repository,
        "debtor",
        "creditor",
        "BYN",
    ) == [1]


async def test_register_outgoing_payment_notifies_creditor(monkeypatch):
    repository = make_repository()
    debtor, creditor = add_people(repository)
    add_bill(repository, 1, 1000)
    notification = MagicMock(chat_id=CREDITOR_TELEGRAM_ID, message_id=77)
    send_notification = AsyncMock(return_value=notification)
    monkeypatch.setattr(
        payment_service,
        "send_bill_notification",
        send_notification,
    )

    payment, settlement = await payment_service.register_outgoing_payment(
        MagicMock(),
        repository,
        debtor,
        creditor,
        400,
        "BYN",
        None,
    )

    assert settlement is None
    assert payment.status == PaymentStatus.PENDING
    assert payment.bill_ids == [1]
    assert payment.confirmation_message_id == 77
    assert len(repository.db.delayed_actions) == 1
    markup = send_notification.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == (
        f"bills:pay_confirm|{payment.id}"
    )


async def test_register_received_payment_settles_and_notifies(monkeypatch):
    repository = make_repository()
    debtor, creditor = add_people(repository)
    bill = add_bill(repository, 1, 1000)
    notify_confirmed = AsyncMock()
    bot = MagicMock()
    monkeypatch.setattr(
        payment_service,
        "notify_payment_confirmed",
        notify_confirmed,
    )

    payment, settlement = await payment_service.register_received_payment(
        bot,
        repository,
        creditor,
        debtor,
        1000,
        "BYN",
        None,
    )

    assert settlement.allocations == [(1, 1000)]
    assert bill.closed is True
    notify_confirmed.assert_awaited_once_with(
        bot,
        repository,
        payment,
        creditor,
        settlement,
    )


async def test_payment_details_api_is_owner_only(monkeypatch):
    repository = make_repository()
    debtor, creditor = add_people(repository)
    stranger = BillPerson(
        id="stranger",
        display_name="Паша",
        telegram_id=303,
        description="Скрытые реквизиты",
    )
    repository.db.bill_persons.append(stranger)
    add_bill(repository, 1, 1000)
    monkeypatch.setattr(
        server,
        "_get_tg_user_from_request",
        lambda _: {
            "id": DEBTOR_TELEGRAM_ID,
            "first_name": "Дима",
            "username": "dima",
        },
    )

    own = await server.handle_bills_payment_details_get(
        make_request(repository)
    )
    target = await server.handle_bills_payment_details_get(
        make_request(
            repository,
            match_info={"person_id": creditor.id},
        )
    )
    denied = await server.handle_bills_payment_details_get(
        make_request(
            repository,
            match_info={"person_id": stranger.id},
        )
    )

    assert response_json(own)["payment_details"] == debtor.description
    assert response_json(target)["payment_details"] == creditor.description
    assert denied.status == 403


async def test_payment_details_api_updates_only_caller(monkeypatch):
    repository = make_repository()
    debtor, creditor = add_people(repository)
    monkeypatch.setattr(
        server,
        "_get_tg_user_from_request",
        lambda _: {
            "id": DEBTOR_TELEGRAM_ID,
            "first_name": "Дима",
            "username": "dima",
        },
    )

    response = await server.handle_bills_payment_details_update(
        make_request(
            repository,
            data={"payment_details": "  Новые реквизиты  "},
        )
    )

    assert response.status == 200
    assert debtor.description == "Новые реквизиты"
    assert creditor.description == "СБП +375 29 123-45-67"


async def test_web_partial_payment_uses_validated_debt_scope(monkeypatch):
    repository = make_repository()
    add_people(repository, creditor_telegram_id=None)
    bill = add_bill(repository, 1, 1000)
    monkeypatch.setattr(
        server,
        "_get_tg_user_from_request",
        lambda _: {
            "id": DEBTOR_TELEGRAM_ID,
            "first_name": "Дима",
            "username": "dima",
        },
    )

    response = await server.handle_bills_payment_create(
        make_request(
            repository,
            data={
                "creditor": "creditor",
                "amount_minor": 400,
                "currency": "BYN",
                "bill_ids": [1],
            },
        )
    )

    payload = response_json(response)
    assert response.status == 200
    assert payload["auto_confirmed"] is True
    assert payload["allocations"] == [{"bill_id": 1, "amount_minor": 400}]
    assert bill.closed is False
    balances, _ = compute_bill_balances(
        repository.db.bills_v2,
        repository.db.bill_payments_v2,
    )
    assert balances[1]["debtor"]["creditor"] == 600


async def test_web_payment_rejects_foreign_bill_scope(monkeypatch):
    repository = make_repository()
    add_people(repository)
    add_bill(repository, 1, 1000)
    monkeypatch.setattr(
        server,
        "_get_tg_user_from_request",
        lambda _: {
            "id": DEBTOR_TELEGRAM_ID,
            "first_name": "Дима",
            "username": "dima",
        },
    )

    response = await server.handle_bills_payment_create(
        make_request(
            repository,
            data={
                "creditor": "creditor",
                "amount_minor": 400,
                "currency": "BYN",
                "bill_ids": [999],
            },
        )
    )

    assert response.status == 400
    assert repository.db.bill_payments_v2 == []


async def test_web_payment_rejects_invalid_amount(monkeypatch):
    repository = make_repository()
    add_people(repository)
    add_bill(repository, 1, 1000)
    monkeypatch.setattr(
        server,
        "_get_tg_user_from_request",
        lambda _: {
            "id": DEBTOR_TELEGRAM_ID,
            "first_name": "Дима",
            "username": "dima",
        },
    )

    response = await server.handle_bills_payment_create(
        make_request(
            repository,
            data={
                "creditor": "creditor",
                "amount_minor": 0,
                "currency": "BYN",
            },
        )
    )

    assert response.status == 400
    assert repository.db.bill_payments_v2 == []


async def test_web_payment_confirmation_uses_fifo_settlement(monkeypatch):
    repository = make_repository()
    add_people(repository)
    add_bill(repository, 1, 1000)
    payment = BillPaymentV2(
        id="pending-payment",
        debtor="debtor",
        creditor="creditor",
        amount_minor=400,
        currency="BYN",
        status=PaymentStatus.PENDING,
        bill_ids=[1],
    )
    repository.db.bill_payments_v2.append(payment)
    notify_confirmed = AsyncMock()
    monkeypatch.setattr(
        payment_service,
        "notify_payment_confirmed",
        notify_confirmed,
    )
    monkeypatch.setattr(
        server,
        "_get_tg_user_from_request",
        lambda _: {
            "id": CREDITOR_TELEGRAM_ID,
            "first_name": "Кирилл",
            "username": "kirill",
        },
    )

    response = await server.handle_bills_payment_confirm(
        make_request(
            repository,
            match_info={"pid": payment.id},
        )
    )

    payload = response_json(response)
    assert response.status == 200
    assert payload["allocations"] == [{"bill_id": 1, "amount_minor": 400}]
    assert payment not in repository.db.bill_payments_v2
    balances, _ = compute_bill_balances(
        repository.db.bills_v2,
        repository.db.bill_payments_v2,
    )
    assert balances[1]["debtor"]["creditor"] == 600


async def test_web_received_partial_payment_is_visible_in_bill(monkeypatch):
    repository = make_repository()
    add_people(repository)
    add_bill(repository, 1, 1000)
    monkeypatch.setattr(
        payment_service,
        "notify_payment_confirmed",
        AsyncMock(),
    )
    monkeypatch.setattr(
        server,
        "_get_tg_user_from_request",
        lambda _: {
            "id": CREDITOR_TELEGRAM_ID,
            "first_name": "Кирилл",
            "username": "kirill",
        },
    )

    response = await server.handle_bills_payment_received(
        make_request(
            repository,
            data={
                "debtor": "debtor",
                "amount_minor": 350,
                "currency": "BYN",
            },
        )
    )

    payload = response_json(response)
    assert response.status == 200
    assert payload["allocations"] == [{"bill_id": 1, "amount_minor": 350}]
    assert any(
        item.bill_ids == [1] and item.amount_minor == 350
        for item in repository.db.bill_payments_v2
    )


async def test_chat_payment_details_commands():
    repository = make_repository()

    saved, saved_ok = await invoke(
        BillsFeature,
        "/bills details СБП по номеру телефона",
        repository,
        user_id=DEBTOR_TELEGRAM_ID,
        chat_id=DEBTOR_TELEGRAM_ID,
    )
    shown, shown_ok = await invoke(
        BillsFeature,
        "/bills details",
        repository,
        user_id=DEBTOR_TELEGRAM_ID,
        chat_id=DEBTOR_TELEGRAM_ID,
    )

    assert saved_ok is True
    assert "сохранены" in saved.lower()
    assert shown_ok is True
    assert "СБП по номеру телефона" in shown


async def test_chat_payment_details_are_not_shown_in_group():
    repository = make_repository()
    debtor, _ = add_people(repository)
    debtor.description = "Секретный номер карты"

    shown, shown_ok = await invoke(
        BillsFeature,
        "/bills details",
        repository,
        user_id=DEBTOR_TELEGRAM_ID,
    )

    assert shown_ok is True
    assert "Секретный номер карты" not in shown
    assert "не показываю" in shown


def test_migration_restores_legacy_payment_details():
    repository = make_repository()
    migrated = repository._migrate({
        "version": 44,
        "details_infos": [
            {
                "name": "Димон",
                "description": "Старая карта",
            },
            {
                "name": "kirill",
                "description": "Не заменять",
            },
        ],
        "users": [
            {
                "id": DEBTOR_TELEGRAM_ID,
                "username": "dima",
                "stand_name": "Дмитрий",
                "stand_aliases": ["Димон"],
            }
        ],
        "bill_persons": [
            {
                "id": "debtor",
                "display_name": "Дима",
                "telegram_id": DEBTOR_TELEGRAM_ID,
                "telegram_username": "dima",
                "description": "",
                "aliases": [],
            },
            {
                "id": "creditor",
                "display_name": "Кирилл",
                "telegram_username": "kirill",
                "description": "Новые реквизиты",
                "aliases": [],
            },
        ],
    })

    assert migrated["version"] == 46
    assert migrated["bill_persons"][0]["description"] == "Старая карта"
    assert migrated["bill_persons"][1]["description"] == "Новые реквизиты"
