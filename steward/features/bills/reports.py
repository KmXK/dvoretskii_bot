from steward.data.models.bill import Bill, DetailsInfo, Payment
from steward.features.bills.amounts import escape_md_block, md_escape
from steward.features.bills.payments import (
    apply_payments,
    debts_from_transactions,
    debts_to_list,
    net_direct_debts,
    participants_from_transactions,
    payments_relevant_to_participants,
)
from steward.features.bills.sheets import (
    load_all_transactions,
    parse_transactions_from_sheet,
    read_bill_raw_rows,
)
from steward.helpers.google_drive import get_file_link
from steward.helpers.pagination import PageFormatContext


def format_report(
    debts_list: list[tuple[str, str, float]],
    payments: list[Payment],
    details_infos: list[DetailsInfo],
    title: str | None = None,
    file_link: str | None = None,
    closable_bill_ids: list[int] | None = None,
    debts_list_all: list[tuple[str, str, float]] | None = None,
    closable_bill_ids_all: list[int] | None = None,
) -> str:
    lines = []
    if title:
        lines.append(md_escape(title))
        lines.append("")
    if debts_list or closable_bill_ids:
        lines.append("📊 Кто кому должен:")
        if debts_list:
            lines.append("```")
            col_d, col_c, col_a = 18, 18, 10
            lines.append(f"{'Должник':<{col_d}} {'Кому':<{col_c}} {'Сумма':>{col_a}}")
            lines.append("-" * (col_d + col_c + col_a + 2))
            for debtor, creditor, amount in sorted(
                debts_list, key=lambda x: (-x[2], x[0], x[1])
            ):
                lines.append(
                    f"{debtor[:col_d]:<{col_d}} {creditor[:col_c]:<{col_c}} {amount:>{col_a}.2f}"
                )
            lines.append("```")
        elif closable_bill_ids:
            ids_str = " ".join(str(i) for i in sorted(closable_bill_ids))
            lines.append(f"`/bill close {ids_str}`")
        lines.append("")
    if debts_list_all is not None:
        lines.append("📊 Кто кому должен (все счета):")
        if debts_list_all:
            lines.append("```")
            col_d, col_c, col_a = 18, 18, 10
            lines.append(f"{'Должник':<{col_d}} {'Кому':<{col_c}} {'Сумма':>{col_a}}")
            lines.append("-" * (col_d + col_c + col_a + 2))
            for debtor, creditor, amount in sorted(
                debts_list_all, key=lambda x: (-x[2], x[0], x[1])
            ):
                lines.append(
                    f"{debtor[:col_d]:<{col_d}} {creditor[:col_c]:<{col_c}} {amount:>{col_a}.2f}"
                )
            lines.append("```")
        elif closable_bill_ids_all:
            ids_str = " ".join(str(i) for i in sorted(closable_bill_ids_all))
            lines.append(f"`/bill close {ids_str}`")
        lines.append("")
    if payments:
        lines.append("💸 Совершенные переводы:")
        lines.append("```")
        lines.append(f"{'Кто заплатил':<18} {'Кому':<18} {'Сумма':<12} {'Дата':<15}")
        lines.append("-" * 63)
        for p in sorted(payments, key=lambda x: x.timestamp):
            date_str = p.timestamp.strftime("%Y-%m-%d %H:%M")
            cred = (p.creditor or "—")[:16]
            lines.append(
                f"{p.person[:16]:<18} {cred:<18} {p.amount:<12.2f} {date_str:<15}"
            )
        lines.append("```")
    if debts_list and details_infos:
        creditors = {c for (_, c, _) in debts_list}
        relevant = [d for d in details_infos if d.name in creditors]
        if relevant:
            lines.append("💳 Данные для перевода:")
            for d in relevant:
                lines.append(f"• {md_escape(d.name)}: {md_escape(d.description)}")
            lines.append("")
    if not debts_list and not payments and not (debts_list and details_infos):
        lines.append("Нет долгов и переводов.")
    if file_link:
        lines.append(f"🔗 {md_escape(file_link)}")
    return "\n".join(lines).strip()


def generate_main_report_text(
    bills: list[Bill],
    payments: list[Payment],
    details_infos: list[DetailsInfo],
) -> str:
    all_tx = load_all_transactions(bills)
    participants = participants_from_transactions(all_tx)
    payments_relevant = payments_relevant_to_participants(payments, participants)
    debts = debts_from_transactions(all_tx)
    debts = apply_payments(debts, payments)
    debts = net_direct_debts(debts)
    debts_list = debts_to_list(debts)
    closable = [b.id for b in bills] if not debts_list else None
    return format_report(
        debts_list,
        payments_relevant,
        details_infos,
        title="📋 Общий отчет",
        closable_bill_ids=closable,
    )


def generate_single_bill_report_text(
    bill: Bill,
    all_bills: list[Bill],
    payments: list[Payment],
    details_infos: list[DetailsInfo],
) -> str:
    raw_rows = read_bill_raw_rows(bill.file_id)
    transactions = parse_transactions_from_sheet(raw_rows[:-1] if raw_rows else [])
    all_tx = load_all_transactions(all_bills)
    debts_this = debts_from_transactions(transactions)
    debts_this = apply_payments(debts_this, payments, clamp_zero=True)
    debts_this = net_direct_debts(debts_this)
    debts_list_this = debts_to_list(debts_this)
    debts_all = debts_from_transactions(all_tx)
    debts_all = apply_payments(debts_all, payments)
    debts_all = net_direct_debts(debts_all)
    debts_list_all = debts_to_list(debts_all)
    closable_this = [bill.id] if not debts_list_this else None
    closable_all = [b.id for b in all_bills] if not debts_list_all else None
    participants = participants_from_transactions(transactions)
    payments_relevant = payments_relevant_to_participants(payments, participants)
    return format_report(
        debts_list_this,
        payments_relevant,
        details_infos,
        title=f"📋 Счет: {bill.name}",
        file_link=get_file_link(bill.file_id),
        closable_bill_ids=closable_this,
        debts_list_all=debts_list_all,
        closable_bill_ids_all=closable_all,
    )


def report_for_target(
    target: str,
    bills: list[Bill],
    payments: list[Payment],
    details_infos: list[DetailsInfo],
) -> str | None:
    if target == "общий":
        return generate_main_report_text(bills, payments, details_infos)
    try:
        bill_id = int(target)
    except ValueError:
        return None
    bill = next((b for b in bills if b.id == bill_id), None)
    if bill is None:
        return None
    return generate_single_bill_report_text(bill, bills, payments, details_infos)


def format_bill_page(ctx: PageFormatContext[Bill]) -> str:
    from steward.helpers.formats import format_lined_list

    if not ctx.data:
        return "Нет счетов"
    items = []
    for bill in ctx.data:
        link = get_file_link(bill.file_id)
        name = escape_md_block(bill.name)
        if link:
            name = f"[{name}]({link})"
        items.append((bill.id, name))
    return format_lined_list(items=items, delimiter=": ")
