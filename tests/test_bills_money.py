"""Tests for steward/helpers/bills_money.py — int kopeck arithmetic."""
from steward.data.models.bill_v2 import (
    BillItemAssignment,
    BillTransaction,
    UNKNOWN_PERSON_ID,
)
from steward.helpers.bills_money import (
    apply_payments,
    compute_bill_debts,
    minor_from_float,
    minor_to_display,
    net_debts,
    split_minor,
)


class TestSplitMinor:
    def test_even_split(self):
        assert split_minor(900, 3) == [300, 300, 300]

    def test_uneven_split_distributes_remainder(self):
        assert split_minor(1000, 3) == [334, 333, 333]

    def test_zero(self):
        assert split_minor(0, 3) == [0, 0, 0]

    def test_one_part(self):
        assert split_minor(1234, 1) == [1234]

    def test_zero_parts(self):
        assert split_minor(100, 0) == []


class TestMinorConversion:
    def test_from_float_round_half_up(self):
        assert minor_from_float(3.0) == 300
        assert minor_from_float(0.005) == 1  # round half up
        assert minor_from_float(1.50) == 150

    def test_to_display_byn(self):
        assert minor_to_display(300, "BYN") == "3 р"
        assert minor_to_display(150, "BYN") == "1.50 р"

    def test_to_display_usd(self):
        assert minor_to_display(300, "USD") == "$3"
        assert minor_to_display(150, "USD") == "$1.50"

    def test_to_display_negative(self):
        assert minor_to_display(-300, "BYN") == "-3 р"


class TestComputeBillDebts:
    def test_simple_split(self):
        # Kirill paid 300 (3 BYN), shared with Lesha
        tx = BillTransaction(
            id="1",
            item_name="Мороженое",
            creditor="kirill",
            unit_price_minor=300,
            quantity=1,
            assignments=[BillItemAssignment(unit_count=1, debtors=["kirill", "lesha"])],
        )
        debts = compute_bill_debts([tx])
        # Lesha owes Kirill 150
        assert debts["lesha"]["kirill"] == 150
        # Kirill doesn't owe himself
        assert "kirill" not in debts or "kirill" not in debts.get("kirill", {})

    def test_per_person_split_separate_rows(self):
        # "по 3 рубля" → two rows of qty=1, one per person
        tx1 = BillTransaction(
            id="1", item_name="Мороженое", creditor="kirill",
            unit_price_minor=300, quantity=1,
            assignments=[BillItemAssignment(unit_count=1, debtors=["kirill"])],
        )
        tx2 = BillTransaction(
            id="2", item_name="Мороженое", creditor="kirill",
            unit_price_minor=300, quantity=1,
            assignments=[BillItemAssignment(unit_count=1, debtors=["lesha"])],
        )
        debts = compute_bill_debts([tx1, tx2])
        # Lesha owes Kirill 300 (one full ice cream)
        assert debts["lesha"]["kirill"] == 300
        # Kirill paid for himself, no debt
        assert "kirill" not in debts

    def test_multi_assignment_hookah(self):
        # 3 hookahs, 2 for Dima+Egor, 1 for Dima+Egor+Kirill, paid by Pasha
        tx = BillTransaction(
            id="1",
            item_name="Кальян",
            creditor="pasha",
            unit_price_minor=2000,  # 20 BYN per hookah
            quantity=3,
            assignments=[
                BillItemAssignment(unit_count=2, debtors=["dima", "egor"]),
                BillItemAssignment(unit_count=1, debtors=["dima", "egor", "kirill"]),
            ],
        )
        debts = compute_bill_debts([tx])
        # 2 hookahs * 20 BYN = 40 BYN split between Dima+Egor → 20 BYN each
        # 1 hookah * 20 BYN = 20 BYN split between Dima+Egor+Kirill → 6.67 each
        # split_minor(2000, 3) = [667, 667, 666]
        # Dima: 2000 + 667 = 2667
        # Egor: 2000 + 667 = 2667
        # Kirill: 666
        assert debts["dima"]["pasha"] == 2667
        assert debts["egor"]["pasha"] == 2667
        assert debts["kirill"]["pasha"] == 666

    def test_skip_unknown_creditor(self):
        tx = BillTransaction(
            id="1", item_name="X", creditor=UNKNOWN_PERSON_ID,
            unit_price_minor=100, quantity=1,
            assignments=[BillItemAssignment(unit_count=1, debtors=["a", "b"])],
        )
        assert compute_bill_debts([tx]) == {}

    def test_skip_unassigned(self):
        tx = BillTransaction(
            id="1", item_name="X", creditor="a",
            unit_price_minor=100, quantity=1,
            assignments=[BillItemAssignment(unit_count=1, debtors=[])],
        )
        assert compute_bill_debts([tx]) == {}


class TestNetDebts:
    def test_collapses_mutual(self):
        debts = {
            "a": {"b": 500},
            "b": {"a": 200},
        }
        net = net_debts(debts)
        assert dict(net) == {"a": {"b": 300}}

    def test_no_collapse_when_one_way(self):
        debts = {"a": {"b": 500}}
        net = net_debts(debts)
        assert dict(net) == {"a": {"b": 500}}


class TestApplyPayments:
    def test_subtracts_confirmed(self):
        from steward.data.models.bill_v2 import BillPaymentV2

        debts = {"a": {"b": 500}}
        payment = BillPaymentV2(
            id="p1", debtor="a", creditor="b",
            amount_minor=200, status="confirmed",
        )
        result = apply_payments(debts, [payment])
        assert result["a"]["b"] == 300

    def test_ignores_pending(self):
        from steward.data.models.bill_v2 import BillPaymentV2

        debts = {"a": {"b": 500}}
        payment = BillPaymentV2(
            id="p1", debtor="a", creditor="b",
            amount_minor=200, status="pending",
        )
        result = apply_payments(debts, [payment])
        assert result["a"]["b"] == 500

    def test_clamps_to_zero(self):
        from steward.data.models.bill_v2 import BillPaymentV2

        debts = {"a": {"b": 100}}
        payment = BillPaymentV2(
            id="p1", debtor="a", creditor="b",
            amount_minor=500, status="confirmed",
        )
        result = apply_payments(debts, [payment], clamp_zero=True)
        assert result["a"]["b"] == 0

    def test_refund_increases_reverse_debt(self):
        from steward.data.models.bill_v2 import BillPaymentV2

        debts = {"a": {"b": 500}}
        # b refunded 200 to a; this means a owes b 200 more (debt(a→b) goes up).
        payment = BillPaymentV2(
            id="p1", debtor="b", creditor="a",
            amount_minor=200, status="confirmed", is_refund=True,
        )
        result = apply_payments(debts, [payment])
        assert result["a"]["b"] == 700

    def test_refund_no_op_when_no_reverse_debt(self):
        from steward.data.models.bill_v2 import BillPaymentV2

        debts = {"a": {"b": 500}}
        # No debt(c→x) exists so refund finds nothing to attach to.
        payment = BillPaymentV2(
            id="p1", debtor="c", creditor="x",
            amount_minor=200, status="confirmed", is_refund=True,
        )
        result = apply_payments(debts, [payment])
        assert result == {"a": {"b": 500}}

class TestDistributePaymentAmount:
    def test_exact_match(self):
        from steward.helpers.bills_money import distribute_payment_amount
        allocs, residual = distribute_payment_amount([(1, 2000), (2, 1000)], 3000)
        assert allocs == [(1, 2000), (2, 1000)]
        assert residual == 0

    def test_underpay_fifo(self):
        from steward.helpers.bills_money import distribute_payment_amount
        allocs, residual = distribute_payment_amount([(1, 2000), (2, 1000)], 1500)
        assert allocs == [(1, 1500)]
        assert residual == 0

    def test_underpay_spans_bills(self):
        from steward.helpers.bills_money import distribute_payment_amount
        # 35 paying 20+10 from older first; 25 covers #1 fully + 5 of #2
        allocs, residual = distribute_payment_amount([(1, 2000), (2, 1000)], 2500)
        assert allocs == [(1, 2000), (2, 500)]
        assert residual == 0

    def test_overpay_residual(self):
        from steward.helpers.bills_money import distribute_payment_amount
        allocs, residual = distribute_payment_amount([(1, 2000), (2, 1000)], 3500)
        assert allocs == [(1, 2000), (2, 1000)]
        assert residual == 500

    def test_zero_amount(self):
        from steward.helpers.bills_money import distribute_payment_amount
        allocs, residual = distribute_payment_amount([(1, 2000)], 0)
        assert allocs == []
        assert residual == 0

    def test_no_debt(self):
        from steward.helpers.bills_money import distribute_payment_amount
        allocs, residual = distribute_payment_amount([], 500)
        assert allocs == []
        assert residual == 500


    def test_mixed_forward_and_refund(self):
        from steward.data.models.bill_v2 import BillPaymentV2

        debts = {"a": {"b": 500}}
        forward = BillPaymentV2(
            id="p1", debtor="a", creditor="b",
            amount_minor=300, status="confirmed",
        )
        refund = BillPaymentV2(
            id="p2", debtor="b", creditor="a",
            amount_minor=50, status="confirmed", is_refund=True,
        )
        result = apply_payments(debts, [forward, refund])
        assert result["a"]["b"] == 250
