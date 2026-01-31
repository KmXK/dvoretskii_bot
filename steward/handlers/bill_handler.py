import logging
import re
from collections import defaultdict

from steward.bot.context import ChatBotContext
from steward.data.models.bill import Bill, DetailsInfo, Payment, Transaction
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.google_drive import (
    find_file_in_folder,
    get_file_link,
    is_available as google_drive_available,
    read_spreadsheet_values,
)
from steward.helpers.pagination import PageFormatContext, Paginator
from steward.helpers.tg_update_helpers import get_message, is_valid_markdown, split_long_message
from steward.helpers.validation import check, validate_message_text
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.steps.keyboard_step import KeyboardStep
from steward.session.steps.question_step import QuestionStep

logger = logging.getLogger(__name__)

FINANCES_FOLDER_ID = "1_YgOgjiqOyMZ1_jVAND_7HG9GfE7MpHX"

_AMOUNT_RE = re.compile(r"[\d\s]+[,.]?\d*")


def _md_escape(s: str) -> str:
    for c in "_*`[":
        s = s.replace(c, "\\" + c)
    return s


def _parse_amount(s: str) -> float:
    s = s.strip().replace(",", ".")
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


def debts_from_transactions(transactions: list[Transaction]) -> dict[str, dict[str, float]]:
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
    total_by_debtor: dict[str, float] = defaultdict(float)
    for p in payments:
        total_by_debtor[p.person] += p.amount
    for debtor in list(debts.keys()):
        if debtor not in total_by_debtor:
            continue
        remaining = total_by_debtor[debtor]
        for creditor in sorted(debts[debtor].keys()):
            if remaining <= 0:
                break
            amt = debts[debtor][creditor]
            if amt > 0:
                red = min(amt, remaining)
                debts[debtor][creditor] -= red
                remaining -= red
    return debts


def net_debts(debts: dict[str, dict[str, float]]) -> list[tuple[str, str, float]]:
    net: dict[str, float] = defaultdict(float)
    for debtor, creds in debts.items():
        for creditor, amount in creds.items():
            if amount > 0.01:
                net[debtor] -= amount
                net[creditor] += amount
    creditors = {k: v for k, v in net.items() if v > 0.01}
    debtors = {k: -v for k, v in net.items() if v < -0.01}
    result = []
    cr_list = sorted(creditors.items(), key=lambda x: -x[1])
    dr_list = sorted(debtors.items(), key=lambda x: -x[1])
    i = j = 0
    while i < len(cr_list) and j < len(dr_list):
        cred, c_val = cr_list[i]
        deb, d_val = dr_list[j]
        if c_val < 0.01:
            i += 1
            continue
        if d_val < 0.01:
            j += 1
            continue
        amt = min(c_val, d_val)
        result.append((deb, cred, amt))
        c_val -= amt
        d_val -= amt
        cr_list[i] = (cred, c_val)
        dr_list[j] = (deb, d_val)
        if c_val < 0.01:
            i += 1
        if d_val < 0.01:
            j += 1
    return result


def _format_report(
    netted: list[tuple[str, str, float]],
    payments: list[Payment],
    details_infos: list[DetailsInfo],
    title: str | None = None,
    file_link: str | None = None,
) -> str:
    lines = []
    if title:
        lines.append(_md_escape(title))
        lines.append("")
    if netted:
        lines.append("📊 Кто кому должен:")
        lines.append("```")
        lines.append(f"{'Должник':<18} {'Кому':<18} {'Сумма':<12}")
        lines.append("-" * 48)
        for debtor, creditor, amount in sorted(netted, key=lambda x: (-x[2], x[0], x[1])):
            lines.append(f"{debtor[:16]:<18} {creditor[:16]:<18} {amount:<12.2f}")
        lines.append("```")
        lines.append("")
    if payments:
        lines.append("💸 Совершенные переводы:")
        lines.append("```")
        lines.append(f"{'Кто заплатил':<18} {'Кому':<18} {'Сумма':<12} {'Дата':<15}")
        lines.append("-" * 63)
        for p in sorted(payments, key=lambda x: x.timestamp):
            date_str = p.timestamp.strftime("%Y-%m-%d %H:%M")
            cred = (p.creditor or "—")[:16]
            lines.append(f"{p.person[:16]:<18} {cred:<18} {p.amount:<12.2f} {date_str:<15}")
        lines.append("```")
        lines.append("")
    if netted and details_infos:
        creditors = {c for (_, c, _) in netted}
        relevant = [d for d in details_infos if d.name in creditors]
        if relevant:
            lines.append("💳 Данные для перевода:")
            for d in relevant:
                lines.append(f"• {_md_escape(d.name)}: {_md_escape(d.description)}")
    if not netted and not payments and not (netted and details_infos):
        lines.append("Нет долгов и переводов.")
    if file_link:
        lines.append("")
        lines.append(f"🔗 {_md_escape(file_link)}")
    return "\n".join(lines).strip()


def _get_bills_folder_id() -> str:
    return FINANCES_FOLDER_ID


def _get_folder_link(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def _read_bill_raw_rows(file_id: str) -> list[list[str]]:
    rows = read_spreadsheet_values(file_id)
    return rows or []


def _load_bill_transactions(file_id: str) -> list[Transaction]:
    rows = _read_bill_raw_rows(file_id)
    if rows:
        rows = rows[:-1]
    return parse_transactions_from_sheet(rows)


def _format_raw_rows(rows: list[list[str]]) -> str:
    if not rows:
        return "Файл пуст"
    lines = ["```"]
    for i, row in enumerate(rows):
        cells = [str(c or "").strip()[:20] for c in (row[:4] if row else [])]
        while len(cells) < 4:
            cells.append("")
        lines.append(f"{cells[0]:<20} | {cells[1]:<12} | {cells[2]:<25} | {cells[3]}")
    lines.append("```")
    return "\n".join(lines)


def _load_all_transactions(bills: list[Bill]) -> list[Transaction]:
    all_tx = []
    for bill in bills:
        all_tx.extend(_load_bill_transactions(bill.file_id))
    return all_tx


def _build_report_for_transactions(
    transactions: list[Transaction],
    payments: list[Payment],
    details_infos: list[DetailsInfo],
    title: str | None = None,
    file_link: str | None = None,
) -> str:
    debts = debts_from_transactions(transactions)
    debts = apply_payments(debts, payments)
    netted = net_debts(debts)
    return _format_report(netted, payments, details_infos, title=title, file_link=file_link)


def _format_bill_page(ctx: PageFormatContext[Bill]) -> str:
    from steward.helpers.formats import format_lined_list

    if not ctx.data:
        return "Нет счетов"
    items = [(bill.id, f"{bill.name} ({get_file_link(bill.file_id) or '—'})") for bill in ctx.data]
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
                        [check(lambda t: len(t.strip()) > 0, "Имя не может быть пустым")]
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
        existing = next((b for b in self.repository.db.bills if b.name.lower() == name.lower()), None)
        if existing:
            existing.file_id = file_id
        else:
            next_id = max((b.id for b in self.repository.db.bills), default=0) + 1
            self.repository.db.bills.append(Bill(id=next_id, name=name, file_id=file_id))
        await self.repository.save()
        link = get_file_link(file_id)
        raw_rows = _read_bill_raw_rows(file_id)
        transactions = parse_transactions_from_sheet(raw_rows)
        report = _build_report_for_transactions(
            transactions,
            self.repository.db.payments,
            self.repository.db.details_infos,
            title=None,
            file_link=link,
        )
        lines = [
            f"✅ Счет '{name}' добавлен.",
            "",
            "📄 Данные с диска:",
            _format_raw_rows(raw_rows),
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
        if parts[1].lower() in ("add", "all", "pay", "details", "help", "report"):
            return False
        if not google_drive_available():
            await context.message.reply_text("Google Drive недоступен")
            return True
        identifier = " ".join(parts[1:]).strip()
        if not identifier:
            return False
        try:
            bill_id = int(identifier)
            bill = next((b for b in self.repository.db.bills if b.id == bill_id), None)
        except ValueError:
            bill = next((b for b in self.repository.db.bills if b.name.lower() == identifier.lower()), None)
        if not bill:
            await context.message.reply_text(f"Счет '{identifier}' не найден")
            return True
        transactions = _load_bill_transactions(bill.file_id)
        report = _build_report_for_transactions(
            transactions,
            self.repository.db.payments,
            self.repository.db.details_infos,
            title=f"📋 Счет: {bill.name}",
            file_link=get_file_link(bill.file_id),
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
        if len(parts) != 1:
            return False
        bills = self.repository.db.bills
        if not bills:
            await context.message.reply_text("Нет счетов")
            return True
        if not google_drive_available():
            await context.message.reply_text("Google Drive недоступен")
            return True
        all_tx = _load_all_transactions(bills)
        report = _build_report_for_transactions(
            all_tx,
            self.repository.db.payments,
            self.repository.db.details_infos,
            title="📋 Отчет по всем должникам",
            file_link=_get_folder_link(_get_bills_folder_id()),
        )
        for i, chunk in enumerate(split_long_message(report)):
            if i == 0:
                await context.message.reply_text(chunk, parse_mode="Markdown")
            else:
                await context.message.chat.send_message(chunk, parse_mode="Markdown")
        return True

    def help(self):
        return "/bill — основной отчёт по всем должникам"


class BillReportAllHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 2 or parts[1].lower() != "report":
            return False
        if not google_drive_available():
            await context.message.reply_text("Google Drive недоступен")
            return True
        bills = self.repository.db.bills
        if not bills:
            await context.message.reply_text("Нет счетов")
            return True
        all_tx = _load_all_transactions(bills)
        report = _build_report_for_transactions(
            all_tx,
            self.repository.db.payments,
            self.repository.db.details_infos,
            title="📋 Отчет по всем счетам",
            file_link=_get_folder_link(_get_bills_folder_id()),
        )
        for i, chunk in enumerate(split_long_message(report)):
            if i == 0:
                await context.message.reply_text(chunk, parse_mode="Markdown")
            else:
                await context.message.chat.send_message(chunk, parse_mode="Markdown")
        return True

    def help(self):
        return "/bill report — сводный отчет по всем счетам"


class BillPayHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                KeyboardStep(
                    "confirm",
                    lambda ctx: self._format_confirmation(ctx),
                    [[("✅ Подтвердить", "confirm_yes", True), ("❌ Отменить", "confirm_no", False)]],
                ),
            ]
        )
        self._pending: dict | None = None

    async def chat(self, context):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.strip().split()
        if len(parts) < 3 or parts[1] != "pay":
            return False
        debtor = parts[2].strip()
        creditor = None
        amount_str = None
        if len(parts) > 3:
            n = parts[3].strip()
            if n.lower() not in ("все", "all"):
                try:
                    float(n)
                    amount_str = n
                except ValueError:
                    creditor = n
                    if len(parts) > 4:
                        amount_str = parts[4].strip()
        if not google_drive_available():
            await context.message.reply_text("Google Drive недоступен")
            return True
        bills = self.repository.db.bills
        all_tx = _load_all_transactions(bills)
        debts = debts_from_transactions(all_tx)
        debts = apply_payments(debts, self.repository.db.payments)
        netted = net_debts(debts)
        relevant = [(d, c, a) for (d, c, a) in netted if d == debtor]
        if creditor:
            relevant = [(d, c, a) for (d, c, a) in relevant if c == creditor]
        if not relevant:
            await context.message.reply_text("Нет подходящего долга для этого платежа")
            return True
        total_debt = sum(a for (_, _, a) in relevant)
        total_paid = sum(
            p.amount
            for p in self.repository.db.payments
            if p.person == debtor and (not creditor or p.creditor == creditor)
        )
        remaining = total_debt - total_paid
        if amount_str is None:
            payment_amount = remaining
        else:
            try:
                payment_amount = float(amount_str)
            except ValueError:
                await context.message.reply_text(f"Неверная сумма: {amount_str}")
                return True
        if payment_amount <= 0 or payment_amount > remaining + 0.01:
            await context.message.reply_text(
                f"Сумма должна быть от 0.01 до {remaining:.2f} (остаток долга)"
            )
            return True
        self._pending = {
            "debtor": debtor,
            "creditor": creditor,
            "amount": payment_amount,
        }
        return await super().chat(context)

    def _format_confirmation(self, ctx: dict) -> str:
        debtor = ctx["debtor"]
        creditor = ctx.get("creditor")
        amount = ctx["amount"]
        lines = ["💳 Подтверждение платежа", "", f"Кто должен: {debtor}"]
        lines.append(f"Кому: {creditor or 'всем'}")
        lines.append(f"Сумма: {amount:.2f}")
        return "\n".join(lines)

    def try_activate_session(self, update, session_context):
        if self._pending:
            session_context.update(self._pending)
            self._pending = None
            return True
        return False

    async def on_session_finished(self, update, session_context):
        if not session_context.get("confirm", False):
            await get_message(update).chat.send_message("Платеж отменен")
            return
        p = Payment(
            person=session_context["debtor"],
            amount=session_context["amount"],
            creditor=session_context.get("creditor"),
        )
        self.repository.db.payments.append(p)
        await self.repository.save()
        cred = session_context.get("creditor") or "указанным"
        await get_message(update).chat.send_message(
            f"✅ Платеж: {p.person} заплатил {p.amount:.2f} — {cred}"
        )

    def help(self):
        return None


class BillDetailsAddHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                QuestionStep(
                    "name",
                    "Введите имя для платежных данных:",
                    filter_answer=validate_message_text(
                        [check(lambda t: len(t.strip()) > 0, "Имя не может быть пустым")]
                    ),
                ),
                QuestionStep(
                    "description",
                    "Введите описание способов перевода:",
                    filter_answer=validate_message_text(
                        [check(lambda t: len(t.strip()) > 0, "Описание не может быть пустым")]
                    ),
                ),
            ]
        )

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "bill"):
            return False
        assert update.message and update.message.text
        parts = update.message.text.split()
        if len(parts) < 3 or parts[1] != "details" or parts[2] != "add":
            return False
        return True

    async def on_session_finished(self, update, session_context):
        info = DetailsInfo(
            name=session_context["name"].strip(),
            description=session_context["description"].strip(),
        )
        existing = next((d for d in self.repository.db.details_infos if d.name == info.name), None)
        if existing:
            existing.description = info.description
        else:
            self.repository.db.details_infos.append(info)
        await self.repository.save()
        await get_message(update).chat.send_message(f"Платежные данные для '{info.name}' сохранены")

    def help(self):
        return None


class BillDetailsEditHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                QuestionStep(
                    "description",
                    lambda ctx: f"Текущее описание для '{ctx['details_info'].name}':\n{ctx['details_info'].description}\n\nВведите новое описание:",
                    filter_answer=validate_message_text(
                        [check(lambda t: len(t.strip()) > 0, "Описание не может быть пустым")]
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
        details_info = next((d for d in self.repository.db.details_infos if d.name == name), None)
        if details_info is None:
            return False
        session_context["details_info"] = details_info
        return True

    async def on_session_finished(self, update, session_context):
        di = session_context["details_info"]
        di.description = session_context["description"].strip()
        await self.repository.save()
        await get_message(update).chat.send_message(f"Платежные данные для '{di.name}' обновлены")

    def help(self):
        return None


class BillHelpHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False
        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 2 or parts[1] != "help":
            return False
        help_text = """📋 /bill

/bill — основной отчёт по всем должникам
/bill all — список всех счетов
/bill report — сводный отчет по всем счетам
/bill {id} или /bill {имя} — отчет по счету
/bill add — добавить счет (имя = имя файла на Google Диске)
/bill pay {кто должен} [кому] [сколько] — зарегистрировать перевод
/bill details add — добавить платежные данные
/bill details edit {имя} — изменить платежные данные"""
        await context.message.reply_text(help_text)
        return True

    def help(self):
        return "/bill help — помощь по /bill"
