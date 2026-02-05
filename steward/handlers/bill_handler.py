import logging
import re
from collections import defaultdict
from typing import Callable

from steward.bot.context import ChatBotContext
from steward.data.models.bill import Bill, DetailsInfo, Payment, Transaction
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.google_drive import (
    find_file_in_folder,
    get_file_link,
    read_spreadsheet_values,
)
from steward.helpers.google_drive import (
    is_available as google_drive_available,
)
from steward.helpers.pagination import PageFormatContext, Paginator
from steward.helpers.tg_update_helpers import (
    get_message,
    is_valid_markdown,
    split_long_message,
)
from steward.helpers.validation import check, validate_message_text
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.steps.question_step import QuestionStep

logger = logging.getLogger(__name__)

FINANCES_FOLDER_ID = "1_YgOgjiqOyMZ1_jVAND_7HG9GfE7MpHX"

_AMOUNT_RE = re.compile(r"[\d\s]+[,.]?\d*")


def _md_escape(s: str) -> str:
    for c in "_*`[":
        s = s.replace(c, "\\" + c)
    return s


def _parse_amount(s: str) -> float:
    s = s.strip().replace("\u00a0", " ").replace(",", ".")
    m = _AMOUNT_RE.search(s)
    if not m:
        raise ValueError(f"Неверная сумма: {s}")
    raw = m.group(0).replace(" ", "").strip()
    value = float(raw)
    if "-" in s[: m.start()]:
        value = -value
    return value


def parse_transactions_from_sheet(rows: list[list[str]]) -> list[Transaction]:
    out = []
    for i, row in enumerate(rows):
        if i == 0 and row and "Наименование" in (row[0] if row else ""):
            continue
        if len(row) < 4:
            continue
        item_name = (row[0] or "").strip()
        if not item_name:
            continue
        try:
            amount = _parse_amount(row[1] or "0")
        except ValueError:
            continue
        debtors_str = (row[2] or "").strip()
        debtors = [d.strip() for d in debtors_str.split(",") if d.strip()]
        creditor = (row[3] or "").strip()
        if not debtors or not creditor:
            continue
        out.append(
            Transaction(
                item_name=item_name,
                amount=amount,
                debtors=debtors,
                creditor=creditor,
            )
        )
    return out


def debts_from_transactions(
    transactions: list[Transaction],
) -> dict[str, dict[str, float]]:
    debts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        per_person = t.amount / len(t.debtors)
        for d in t.debtors:
            if d != t.creditor:
                debts[d][t.creditor] += per_person
    return debts


def apply_payments(
    debts: dict[str, dict[str, float]], payments: list[Payment]
) -> dict[str, dict[str, float]]:
    for p in payments:
        if not p.creditor:
            continue
        if p.person in debts and p.creditor in debts[p.person]:
            debts[p.person][p.creditor] -= p.amount
    return debts


def _amount_per_debtor_for_closed(
    debts_closed: dict[str, dict[str, float]],
    debts_other: dict[str, dict[str, float]],
    payments: list[Payment],
) -> dict[str, float]:
    amount_to_remove: dict[str, float] = defaultdict(float)
    for debtor in set(debts_closed.keys()) | set(debts_other.keys()):
        creds_closed = debts_closed.get(debtor, {})
        creds_other = debts_other.get(debtor, {})
        total_closed_debt = sum(creds_closed.values())
        if total_closed_debt < 0.01:
            continue
        all_creds = sorted(set(creds_closed.keys()) | set(creds_other.keys()))
        total_paid = sum(p.amount for p in payments if p.person == debtor)
        for creditor in all_creds:
            amt_c = creds_closed.get(creditor, 0)
            amt_o = creds_other.get(creditor, 0)
            total_debt = amt_c + amt_o
            if total_debt < 0.01 or total_paid < 0.01:
                continue
            reduce_amt = min(total_debt, total_paid)
            reduce_closed = min(amt_c, reduce_amt)
            amount_to_remove[debtor] += reduce_closed
            total_paid -= reduce_amt
        amount_to_remove[debtor] = min(amount_to_remove[debtor], total_closed_debt)
    return dict(amount_to_remove)


def _payments_to_remove_for_closed(
    amount_per_debtor: dict[str, float],
    payments: list[Payment],
) -> tuple[list[Payment], list[tuple[Payment, float]]]:
    to_remove: list[Payment] = []
    to_reduce: list[tuple[Payment, float]] = []
    sorted_payments = sorted(payments, key=lambda p: p.timestamp)
    consumed: dict[str, float] = defaultdict(float)
    for p in sorted_payments:
        need = amount_per_debtor.get(p.person, 0) - consumed[p.person]
        if need < 0.01:
            continue
        if p.amount <= need + 0.01:
            to_remove.append(p)
            consumed[p.person] += p.amount
        else:
            new_amount = round(p.amount - need, 2)
            if new_amount < 0.01:
                to_remove.append(p)
                consumed[p.person] += p.amount
            else:
                to_reduce.append((p, new_amount))
                consumed[p.person] += need
    return to_remove, to_reduce


def _net_direct_debts(
    debts: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    working: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for debtor, creds in debts.items():
        for creditor, amount in creds.items():
            if amount > 0.01:
                working[debtor][creditor] += amount
            elif amount < -0.01:
                working[creditor][debtor] += -amount
    people = set(working.keys()) | {c for creds in working.values() for c in creds}
    for a in people:
        for b in people:
            if a >= b:
                continue
            a_to_b = working[a].get(b, 0)
            b_to_a = working[b].get(a, 0)
            if a_to_b < 0.01 and b_to_a < 0.01:
                continue
            net = a_to_b - b_to_a
            working[a][b] = max(0, net)
            working[b][a] = max(0, -net)
    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for debtor, creds in working.items():
        for creditor, amount in creds.items():
            if amount > 0.01:
                result[debtor][creditor] = amount
    return {d: dict(cs) for d, cs in result.items() if cs}


def debts_to_list(debts: dict[str, dict[str, float]]) -> list[tuple[str, str, float]]:
    result = []
    for debtor, creds in debts.items():
        for creditor, amount in creds.items():
            if amount > 0.01:
                result.append((debtor, creditor, amount))
    return result


def _bills_closable(
    bill_ids: list[int],
    all_bills: list[Bill],
    load_transactions: Callable[[str], list[Transaction]],
    payments: list[Payment],
) -> bool:
    bills_to_close = [b for b in all_bills if b.id in bill_ids]
    if len(bills_to_close) != len(bill_ids):
        return False
    other_bills = [b for b in all_bills if b.id not in bill_ids]
    tx_closed = []
    for b in bills_to_close:
        tx_closed.extend(load_transactions(b.file_id))
    tx_other = []
    for b in other_bills:
        tx_other.extend(load_transactions(b.file_id))
    debts_closed = debts_from_transactions(tx_closed)
    debts_closed = apply_payments(debts_closed, payments)
    debts_closed = _net_direct_debts(debts_closed)
    remaining = debts_to_list(debts_closed)
    return len(remaining) == 0


def _participants_from_transactions(transactions: list[Transaction]) -> set[str]:
    out: set[str] = set()
    for t in transactions:
        out.update(t.debtors)
        out.add(t.creditor)
    return out


def _payments_relevant_to_participants(
    payments: list[Payment], participants: set[str]
) -> list[Payment]:
    return [
        p
        for p in payments
        if p.person in participants or (p.creditor and p.creditor in participants)
    ]


def _format_report(
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
        lines.append(_md_escape(title))
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
                lines.append(f"• {_md_escape(d.name)}: {_md_escape(d.description)}")
            lines.append("")
    if not debts_list and not payments and not (debts_list and details_infos):
        lines.append("Нет долгов и переводов.")
    if file_link:
        lines.append(f"🔗 {_md_escape(file_link)}")
    return "\n".join(lines).strip()


def _get_bills_folder_id() -> str:
    return FINANCES_FOLDER_ID


def _read_bill_raw_rows(file_id: str) -> list[list[str]]:
    rows = read_spreadsheet_values(file_id)
    return rows or []


def _load_bill_transactions(file_id: str) -> list[Transaction]:
    rows = _read_bill_raw_rows(file_id)
    if rows:
        rows = rows[:-1]
    return parse_transactions_from_sheet(rows)


def _load_all_transactions(bills: list[Bill]) -> list[Transaction]:
    all_tx = []
    for bill in bills:
        all_tx.extend(_load_bill_transactions(bill.file_id))
    return all_tx


def _format_debug_rows(rows: list[list[str]], bill_name: str) -> str:
    lines = [f"🔍 DEBUG [{bill_name}] — строки из таблицы:"]
    if not rows:
        lines.append("(пусто)")
    else:
        for i, row in enumerate(rows):
            row_str = (
                " | ".join(str(cell) for cell in row) if row else "(пустая строка)"
            )
            lines.append(f"{i}: {row_str}")
    return "\n".join(lines)


def _format_bill_page(ctx: PageFormatContext[Bill]) -> str:
    from steward.helpers.formats import format_lined_list

    if not ctx.data:
        return "Нет счетов"
    items = [
        (bill.id, f"{bill.name} ({get_file_link(bill.file_id) or '—'})")
        for bill in ctx.data
    ]
    return format_lined_list(items=items, delimiter=": ")


class BillListViewHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.split()
        if len(parts) != 2 or parts[1].lower() != "all":
            return False
        bills = self.repository.db.bills
        if not bills:
            await context.message.reply_text("Нет счетов")
            return True
        return await self._get_paginator().show_list(context.update)

    async def callback(self, context: ChatBotContext):
        from steward.helpers.keyboard import parse_and_validate_keyboard
        from steward.helpers.pagination import parse_pagination

        if not context.callback_query or not context.callback_query.data:
            return False
        parsed = parse_and_validate_keyboard(
            "bill_list",
            context.callback_query.data,
            parse_func=parse_pagination,
        )
        if parsed is None:
            return False
        return await self._get_paginator().process_parsed_callback(
            context.update,
            parsed,
        )

    def _get_paginator(self) -> Paginator:
        paginator = Paginator(
            unique_keyboard_name="bill_list",
            list_header="📋 Счета",
            page_size=15,
            page_format_func=_format_bill_page,
            always_show_pagination=True,
        )
        paginator.data_func = lambda: sorted(
            self.repository.db.bills,
            key=lambda b: b.id,
        )
        return paginator

    def help(self):
        return "/bill all — список всех счетов"


class BillAddHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                QuestionStep(
                    "name",
                    "Введите имя счета (имя файла на Google Диске):",
                    filter_answer=validate_message_text(
                        [
                            check(
                                lambda t: len(t.strip()) > 0, "Имя не может быть пустым"
                            )
                        ]
                    ),
                ),
            ]
        )

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "bill"):
            return False
        assert update.message and update.message.text
        parts = update.message.text.split()
        if len(parts) < 2 or parts[1] != "add":
            return False
        return True

    async def on_session_finished(self, update, session_context):
        name = session_context["name"].strip()
        if not google_drive_available():
            await get_message(update).chat.send_message("Google Drive недоступен")
            return
        folder_id = _get_bills_folder_id()
        file_id = find_file_in_folder(folder_id, name)
        if not file_id:
            await get_message(update).chat.send_message(
                f"Файл '{name}' не найден в папке «финансы». Создайте его на Google Диске и попробуйте снова."
            )
            return
        existing = next(
            (b for b in self.repository.db.bills if b.name.lower() == name.lower()),
            None,
        )
        if existing:
            existing.file_id = file_id
            bill_id = existing.id
        else:
            bill_id = max((b.id for b in self.repository.db.bills), default=0) + 1
            self.repository.db.bills.append(
                Bill(id=bill_id, name=name, file_id=file_id)
            )
        await self.repository.save()
        link = get_file_link(file_id)
        raw_rows = _read_bill_raw_rows(file_id)
        transactions = parse_transactions_from_sheet(raw_rows)
        debts = debts_from_transactions(transactions)
        debts = apply_payments(debts, self.repository.db.payments)
        debts = _net_direct_debts(debts)
        debts_list = debts_to_list(debts)
        closable = [bill_id] if not debts_list else None
        report = _format_report(
            debts_list,
            [],
            self.repository.db.details_infos,
            file_link=link,
            closable_bill_ids=closable,
        )
        lines = [
            f"✅ Счет '{name}' добавлен.",
            "",
            report,
        ]
        msg = "\n".join(lines)
        for chunk in split_long_message(msg):
            parse_mode = "Markdown" if is_valid_markdown(chunk) else None
            await get_message(update).chat.send_message(chunk, parse_mode=parse_mode)

    def help(self):
        return None


class BillReportHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 2:
            return False
        if parts[1].lower() in (
            "add",
            "all",
            "pay",
            "details",
            "help",
            "report",
            "close",
            "debug",
            "force",
        ):
            return False
        if not google_drive_available():
            await context.message.reply_text("Google Drive недоступен")
            return True
        debug_mode = parts[-1].lower() == "debug"
        identifier_parts = parts[1:-1] if debug_mode else parts[1:]
        identifier = " ".join(identifier_parts).strip()
        if not identifier:
            return False
        try:
            bill_id = int(identifier)
            bill = next((b for b in self.repository.db.bills if b.id == bill_id), None)
        except ValueError:
            bill = next(
                (
                    b
                    for b in self.repository.db.bills
                    if b.name.lower() == identifier.lower()
                ),
                None,
            )
        if not bill:
            await context.message.reply_text(f"Счет '{identifier}' не найден")
            return True
        raw_rows = _read_bill_raw_rows(bill.file_id)
        if debug_mode:
            debug_msg = _format_debug_rows(raw_rows, bill.name)
            for chunk in split_long_message(debug_msg):
                await context.message.chat.send_message(chunk)
        transactions = parse_transactions_from_sheet(raw_rows[:-1] if raw_rows else [])
        all_bills = self.repository.db.bills
        all_tx = _load_all_transactions(all_bills)
        debts_this = debts_from_transactions(transactions)
        debts_this = apply_payments(debts_this, self.repository.db.payments)
        debts_this = _net_direct_debts(debts_this)
        debts_list_this = debts_to_list(debts_this)
        debts_all = debts_from_transactions(all_tx)
        debts_all = apply_payments(debts_all, self.repository.db.payments)
        debts_all = _net_direct_debts(debts_all)
        debts_list_all = debts_to_list(debts_all)
        closable_this = [bill.id] if not debts_list_this else None
        closable_all = [b.id for b in all_bills] if not debts_list_all else None
        participants = _participants_from_transactions(transactions)
        payments_relevant = _payments_relevant_to_participants(
            self.repository.db.payments, participants
        )
        report = _format_report(
            debts_list_this,
            payments_relevant,
            self.repository.db.details_infos,
            title=f"📋 Счет: {bill.name}",
            file_link=get_file_link(bill.file_id),
            closable_bill_ids=closable_this,
            debts_list_all=debts_list_all,
            closable_bill_ids_all=closable_all,
        )
        for i, chunk in enumerate(split_long_message(report)):
            if i == 0:
                await context.message.reply_text(chunk, parse_mode="Markdown")
            else:
                await context.message.chat.send_message(chunk, parse_mode="Markdown")
        return True

    def help(self):
        return None


class BillMainReportHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.split()
        if len(parts) != 1 and not (len(parts) == 2 and parts[1].lower() == "report"):
            return False
        bills = self.repository.db.bills
        if not bills:
            await context.message.reply_text("Нет счетов")
            return True
        if not google_drive_available():
            await context.message.reply_text("Google Drive недоступен")
            return True
        all_tx = _load_all_transactions(bills)
        participants = _participants_from_transactions(all_tx)
        payments_relevant = _payments_relevant_to_participants(
            self.repository.db.payments, participants
        )
        debts = debts_from_transactions(all_tx)
        debts = apply_payments(debts, self.repository.db.payments)
        debts = _net_direct_debts(debts)
        debts_list = debts_to_list(debts)
        closable = [b.id for b in bills] if not debts_list else None
        report = _format_report(
            debts_list,
            payments_relevant,
            self.repository.db.details_infos,
            title="📋 Общий отчет",
            closable_bill_ids=closable,
        )
        for i, chunk in enumerate(split_long_message(report)):
            if i == 0:
                await context.message.reply_text(chunk, parse_mode="Markdown")
            else:
                await context.message.chat.send_message(chunk, parse_mode="Markdown")
        return True

    def help(self):
        return "/bill — основной отчёт по всем должникам"


class BillPayHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.strip().split()
        if len(parts) < 5 or parts[1] != "pay":
            return False
        if len(parts) >= 4 and parts[2] == "force":
            return False
        person = parts[2].strip()
        creditor = parts[3].strip()
        try:
            amount = float(parts[4].replace(",", "."))
        except ValueError:
            await context.message.reply_text(f"Неверная сумма: {parts[4]}")
            return True
        if amount <= 0:
            await context.message.reply_text("Сумма должна быть больше 0")
            return True
        p = Payment(person=person, amount=amount, creditor=creditor)
        self.repository.db.payments.append(p)
        await self.repository.save()
        await context.message.reply_text(
            f"✅ Платеж: {person} → {creditor} {amount:.2f}"
        )
        return True

    def help(self):
        return None


class BillPayForceDeleteHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.strip().split()
        if len(parts) != 5 or parts[1:4] != ["pay", "force", "delete"]:
            return False
        if not self.repository.is_admin(context.message.from_user.id):
            await context.message.reply_text("Эта команда доступна только админам")
            return True
        try:
            count = int(parts[4])
        except ValueError:
            await context.message.reply_text(f"Неверное количество: {parts[5]}")
            return True
        if count <= 0:
            await context.message.reply_text("Количество должно быть больше 0")
            return True
        payments = self.repository.db.payments
        if count > len(payments):
            count = len(payments)
        if count == 0:
            await context.message.reply_text("Нет платежей для удаления")
            return True
        deleted = payments[-count:]
        del payments[-count:]
        await self.repository.save()
        lines = [f"🗑 Удалено {len(deleted)} платежей:"]
        for p in deleted:
            cred = p.creditor or "—"
            date_str = p.timestamp.strftime("%Y-%m-%d %H:%M")
            lines.append(f"• {p.person} → {cred} {p.amount:.2f} ({date_str})")
        await context.message.reply_text("\n".join(lines))
        return True

    def help(self):
        return None


class BillDetailsAddHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                QuestionStep(
                    "description",
                    "Введите описание платежных данных для пользователя:",
                    filter_answer=validate_message_text(
                        [
                            check(
                                lambda t: len(t.strip()) > 0,
                                "Описание не может быть пустым",
                            )
                        ]
                    ),
                ),
            ]
        )

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "bill"):
            return False
        assert update.message and update.message.text
        parts = update.message.text.split(None, 3)
        if len(parts) < 4 or parts[1] != "details" or parts[2] != "add":
            return False
        session_context["name"] = parts[3].strip()
        if not session_context["name"]:
            return False
        return True

    async def on_session_finished(self, update, session_context):
        name = session_context["name"].strip()
        description = session_context["description"].strip()
        existing = next(
            (d for d in self.repository.db.details_infos if d.name == name), None
        )
        if existing:
            existing.description = description
        else:
            self.repository.db.details_infos.append(
                DetailsInfo(name=name, description=description)
            )
        await self.repository.save()
        await get_message(update).chat.send_message(
            f"Платежные данные для '{name}' сохранены"
        )

    def help(self):
        return None


class BillDetailsEditHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                QuestionStep(
                    "description",
                    lambda ctx: (
                        f"Текущее описание для '{ctx['details_info'].name}':\n{ctx['details_info'].description}\n\nВведите новое описание:"
                    ),
                    filter_answer=validate_message_text(
                        [
                            check(
                                lambda t: len(t.strip()) > 0,
                                "Описание не может быть пустым",
                            )
                        ]
                    ),
                ),
            ]
        )

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "bill"):
            return False
        assert update.message and update.message.text
        parts = update.message.text.split()
        if len(parts) < 4 or parts[1] != "details" or parts[2] != "edit":
            return False
        name = " ".join(parts[3:])
        details_info = next(
            (d for d in self.repository.db.details_infos if d.name == name), None
        )
        if details_info is None:
            return False
        session_context["details_info"] = details_info
        return True

    async def on_session_finished(self, update, session_context):
        di = session_context["details_info"]
        di.description = session_context["description"].strip()
        await self.repository.save()
        await get_message(update).chat.send_message(
            f"Платежные данные для '{di.name}' обновлены"
        )

    def help(self):
        return None


class BillCloseHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.strip().split()
        if len(parts) < 3 or parts[1].lower() != "close":
            return False
        if not google_drive_available():
            await context.message.reply_text("Google Drive недоступен")
            return True
        try:
            bill_ids = [int(p) for p in parts[2:]]
        except ValueError:
            await context.message.reply_text(
                "Неверный формат. Используйте: /bill close {id1} {id2} ..."
            )
            return True
        if not bill_ids:
            await context.message.reply_text(
                "Укажите ID счетов для закрытия: /bill close {id1} {id2} ..."
            )
            return True
        bills = self.repository.db.bills
        bills_to_close = [b for b in bills if b.id in bill_ids]
        if len(bills_to_close) != len(bill_ids):
            missing = set(bill_ids) - {b.id for b in bills_to_close}
            await context.message.reply_text(
                f"Счета не найдены: {', '.join(str(i) for i in sorted(missing))}"
            )
            return True
        if not _bills_closable(
            bill_ids,
            bills,
            _load_bill_transactions,
            self.repository.db.payments,
        ):
            await context.message.reply_text(
                "Закрытие невозможно: не все должники совершили переводы "
                "или остаются непогашенные долги. Проверьте отчёт по счёту."
            )
            return True
        bills_to_close_ids = {b.id for b in bills_to_close}
        other_bills = [b for b in bills if b.id not in bills_to_close_ids]
        tx_closed = []
        for b in bills_to_close:
            tx_closed.extend(_load_bill_transactions(b.file_id))
        tx_other = []
        for b in other_bills:
            tx_other.extend(_load_bill_transactions(b.file_id))
        debts_closed = debts_from_transactions(tx_closed)
        debts_other = debts_from_transactions(tx_other)
        amount_per_debtor = _amount_per_debtor_for_closed(
            debts_closed, debts_other, self.repository.db.payments
        )
        to_remove, to_reduce = _payments_to_remove_for_closed(
            amount_per_debtor, self.repository.db.payments
        )
        for p in to_remove:
            self.repository.db.payments.remove(p)
        for p, new_amount in to_reduce:
            p.amount = new_amount
        for b in bills_to_close:
            bills.remove(b)
        await self.repository.save()
        names = ", ".join(b.name for b in bills_to_close)
        await context.message.reply_text(f"✅ Счета закрыты: {names}")
        return True

    def help(self):
        return "/bill close {id1} {id2} ... — закрыть счета"


class BillHelpHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 2 or parts[1] != "help":
            return False
        help_text = """📋 /bill

/bill — общий отчет по всем счетам
/bill all — список всех счетов
/bill {id} — отчет по счету
/bill {id} debug — отчет по счету с выводом сырых данных из таблицы
/bill add — добавить счет (имя = имя файла в папке «финансы»)
/bill pay {кто} {кому} {сумма} — зарегистрировать перевод
/bill pay force delete {count} — удалить последние N платежей (админ)
/bill close {id1} {id2} ... — закрыть счета
/bill details add {пользователь} — добавить платежные данные
/bill details edit {пользователь} — изменить платежные данные"""
        await context.message.reply_text(help_text)
        return True

    def help(self):
        return "/bill help — помощь по /bill"
