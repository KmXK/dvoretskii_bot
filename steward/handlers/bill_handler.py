import logging
from collections import defaultdict

from steward.bot.context import ChatBotContext
from steward.data.models.bill import (
    Bill,
    DetailsInfo,
    Optimization,
    Payment,
    Transaction,
)
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.tg_update_helpers import get_message, is_valid_markdown, split_long_message
from steward.helpers.validation import (
    check,
    try_get,
    validate_message_text,
)
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.steps.keyboard_step import KeyboardStep
from steward.session.steps.question_step import QuestionStep

logger = logging.getLogger(__name__)


def optimize_debts(debts: dict[str, dict[str, float]]) -> list[Optimization]:
    net_balances: dict[str, float] = defaultdict(float)

    for debtor, creditors in debts.items():
        for creditor, amount in creditors.items():
            net_balances[debtor] -= amount
            net_balances[creditor] += amount

    creditors = {k: v for k, v in net_balances.items() if v > 0.01}
    debtors = {k: -v for k, v in net_balances.items() if v < -0.01}

    optimized = []
    creditors_list = sorted(creditors.items(), key=lambda x: x[1], reverse=True)
    debtors_list = sorted(debtors.items(), key=lambda x: x[1], reverse=True)

    i, j = 0, 0
    while i < len(creditors_list) and j < len(debtors_list):
        creditor, creditor_amount = creditors_list[i]
        debtor, debtor_amount = debtors_list[j]

        if creditor_amount < 0.01:
            i += 1
            continue
        if debtor_amount < 0.01:
            j += 1
            continue

        amount = min(creditor_amount, debtor_amount)
        optimized.append(Optimization(debtor=debtor, creditor=creditor, amount=amount))

        creditor_amount -= amount
        debtor_amount -= amount

        creditors_list[i] = (creditor, creditor_amount)
        debtors_list[j] = (debtor, debtor_amount)

        if creditor_amount < 0.01:
            i += 1
        if debtor_amount < 0.01:
            j += 1

    return optimized


def format_bill_report(bill: Bill, details_infos: list[DetailsInfo]) -> str:
    debts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for transaction in bill.transactions:
        amount_per_person = transaction.amount / len(transaction.debtors)
        for debtor in transaction.debtors:
            if debtor != transaction.creditor:
                debts[debtor][transaction.creditor] += amount_per_person

    total_payments_by_debtor: dict[str, float] = defaultdict(float)
    for payment in bill.payments:
        if payment.bill_id == bill.id:
            total_payments_by_debtor[payment.person] += payment.amount

    for debtor in list(debts.keys()):
        if debtor in total_payments_by_debtor:
            total_debt = sum(debts[debtor].values())
            if total_debt > 0:
                payment_remaining = total_payments_by_debtor[debtor]
                for creditor in sorted(debts[debtor].keys()):
                    if payment_remaining <= 0:
                        break
                    debt_amount = debts[debtor][creditor]
                    if debt_amount > 0:
                        reduction = min(debt_amount, payment_remaining)
                        debts[debtor][creditor] -= reduction
                        payment_remaining -= reduction

    lines = [f"📋 Счет: {bill.name} (ID: {bill.id})", ""]

    if bill.transactions:
        lines.append("💳 Транзакции:")
        lines.append("```")
        lines.append(f"{'Товар':<25} {'Сумма':<12} {'Должники':<25} {'Кому':<15}")
        lines.append("-" * 77)

        for transaction in bill.transactions:
            debtors_str = ", ".join(transaction.debtors)
            lines.append(
                f"{transaction.item_name[:23]:<25} "
                f"{transaction.amount:<12.2f} "
                f"{debtors_str[:23]:<25} "
                f"{transaction.creditor[:13]:<15}"
            )
        lines.append("```")

    if debts:
        lines.append("📊 Долги по должникам:")
        lines.append("```")
        lines.append(f"{'Должник':<18} {'Кому':<18} {'Сумма':<12}")
        lines.append("-" * 48)

        for debtor in sorted(debts.keys()):
            for creditor, amount in sorted(debts[debtor].items()):
                if amount > 0.01:
                    lines.append(
                        f"{debtor[:16]:<18} {creditor[:16]:<18} {amount:<12.2f}"
                    )
        lines.append("```")

    if bill.optimizations:
        lines.append("✨ Оптимизированные переводы:")
        lines.append("```")
        lines.append(f"{'Должник':<18} {'Кому':<18} {'Сумма':<12}")
        lines.append("-" * 48)

        grouped_by_debtor = defaultdict(list)
        for opt in bill.optimizations:
            grouped_by_debtor[opt.debtor].append(opt)

        for debtor in sorted(grouped_by_debtor.keys()):
            for opt in sorted(grouped_by_debtor[debtor], key=lambda x: x.creditor):
                lines.append(
                    f"{opt.debtor[:16]:<18} {opt.creditor[:16]:<18} {opt.amount:<12.2f}"
                )
        lines.append("```")

    if bill.optimizations:
        payments_by_debtor_creditor: dict[tuple[str, str], float] = defaultdict(float)
        total_payments_by_debtor: dict[str, float] = defaultdict(float)
        for payment in bill.payments:
            if payment.bill_id == bill.id:
                total_payments_by_debtor[payment.person] += payment.amount
                if payment.creditor:
                    payments_by_debtor_creditor[(payment.person, payment.creditor)] += payment.amount

        remaining_debts = []
        grouped_by_debtor = defaultdict(list)
        for opt in bill.optimizations:
            grouped_by_debtor[opt.debtor].append(opt)

        for debtor in sorted(grouped_by_debtor.keys()):
            for opt in sorted(grouped_by_debtor[debtor], key=lambda x: x.creditor):
                paid_for_this_creditor = payments_by_debtor_creditor.get((debtor, opt.creditor), 0.0)
                remaining = opt.amount - paid_for_this_creditor

                if remaining > 0.01:
                    remaining_debts.append((debtor, opt.creditor, remaining))

        if remaining_debts:
            lines.append("📉 Оставшаяся сумма долга:")
            lines.append("```")
            lines.append(f"{'Должник':<18} {'Кому':<18} {'Остаток':<12}")
            lines.append("-" * 48)

            for debtor, creditor, remaining in remaining_debts:
                lines.append(
                    f"{debtor[:16]:<18} {creditor[:16]:<18} {remaining:<12.2f}"
                )
            lines.append("```")

    if bill.payments:
        lines.append("💸 Платежи:")
        lines.append("```")
        lines.append(f"{'Кто заплатил':<18} {'Кому':<18} {'Сумма':<12} {'Дата':<15}")
        lines.append("-" * 63)

        payments_for_bill = [p for p in bill.payments if p.bill_id == bill.id]
        payments_for_bill.sort(key=lambda x: x.timestamp)

        debtor_optimizations = defaultdict(list)
        for opt in bill.optimizations:
            debtor_optimizations[opt.debtor].append(opt)

        for debtor in debtor_optimizations:
            debtor_optimizations[debtor].sort(key=lambda x: x.creditor)

        for payment in payments_for_bill:
            debtor = payment.person
            date_str = payment.timestamp.strftime("%Y-%m-%d %H:%M")

            if payment.creditor:
                creditor_str = payment.creditor
            elif debtor in debtor_optimizations:
                opts = debtor_optimizations[debtor]
                if len(opts) == 1:
                    creditor_str = opts[0].creditor
                else:
                    creditor_names = ", ".join([opt.creditor for opt in opts])
                    creditor_str = (
                        creditor_names if len(creditor_names) <= 16 else "несколько"
                    )
            else:
                creditor_str = "неизвестно"

            lines.append(
                f"{payment.person[:16]:<18} {creditor_str[:16]:<18} {payment.amount:<12.2f} {date_str:<15}"
            )
        lines.append("```")

    if bill.optimizations and details_infos:
        creditors_in_optimizations = {opt.creditor for opt in bill.optimizations}
        relevant_details = [
            info for info in details_infos if info.name in creditors_in_optimizations
        ]
        if relevant_details:
            lines.append("💳 Платежные данные:")
            for info in relevant_details:
                lines.append(f"• {info.name}: {info.description}")

    return "\n".join(lines)


def parse_transactions(text: str) -> list[Transaction]:
    transactions = []
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]

    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            raise ValueError(f"Неверный формат транзакции: {line}")

        item_name = parts[0]
        try:
            amount = float(parts[1])
        except ValueError:
            raise ValueError(f"Неверная сумма: {parts[1]}")

        debtors = [d.strip() for d in parts[2].split(",") if d.strip()]
        if not debtors:
            raise ValueError(f"Нет должников: {line}")

        creditor = parts[3]

        transactions.append(
            Transaction(
                item_name=item_name, amount=amount, debtors=debtors, creditor=creditor
            )
        )

    return transactions


def format_transactions_for_edit(transactions: list[Transaction]) -> str:
    lines = []
    for t in transactions:
        debtors_str = ", ".join(t.debtors)
        lines.append(f"{t.item_name}|{t.amount}|{debtors_str}|{t.creditor}")
    return "\n".join(lines)


class BillListViewHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) > 1:
            return False

        bills = self.repository.db.bills
        if not bills:
            await context.message.reply_text("Нет сохраненных счетов")
            return True

        lines = ["📋 Список счетов:", ""]
        for bill in bills:
            lines.append(f"• {bill.name} (ID: {bill.id})")

        await context.message.reply_text("\n".join(lines))
        return True

    def help(self):
        return "/bill - посмотреть все счета"


class BillAddHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                QuestionStep(
                    "name",
                    "Введите название счета:",
                    filter_answer=validate_message_text(
                        [
                            check(
                                lambda t: len(t.strip()) > 0,
                                "Название не может быть пустым",
                            )
                        ]
                    ),
                ),
                QuestionStep(
                    "transactions_text",
                    "Введите транзакции в формате:\nнаименование товара|сумма|кто должен(через запятую)|кому должны\nКаждая транзакция с новой строки:",
                    filter_answer=validate_message_text(
                        [
                            try_get(
                                lambda t: parse_transactions(t),
                                "Ошибка парсинга транзакций. Проверьте формат.",
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
        max_id = max((bill.id for bill in self.repository.db.bills), default=0)
        new_id = max_id + 1

        transactions = session_context["transactions_text"]
        bill = Bill(
            id=new_id,
            name=session_context["name"].strip(),
            transactions=transactions,
        )

        debts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for transaction in transactions:
            amount_per_person = transaction.amount / len(transaction.debtors)
            for debtor in transaction.debtors:
                if debtor != transaction.creditor:
                    debts[debtor][transaction.creditor] += amount_per_person

        bill.optimizations = optimize_debts(debts)

        self.repository.db.bills.append(bill)
        await self.repository.save()

        report = format_bill_report(bill, self.repository.db.details_infos)
        chunks = split_long_message(report)
        for chunk in chunks:
            parse_mode = "Markdown" if is_valid_markdown(chunk) else None
            await get_message(update).chat.send_message(chunk, parse_mode=parse_mode)

    def help(self):
        return None


class BillViewHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 2:
            return False

        if parts[1] in ["add", "edit", "person", "pay", "details", "help", "close"]:
            return False

        identifier = parts[1]

        bill = None
        try:
            bill_id = int(identifier)
            bill = next((b for b in self.repository.db.bills if b.id == bill_id), None)
        except ValueError:
            bill = next(
                (b for b in self.repository.db.bills if b.name == identifier), None
            )

        if bill is None:
            await context.message.reply_text(f"Счет '{identifier}' не найден")
            return True

        if not bill.optimizations:
            debts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            for transaction in bill.transactions:
                amount_per_person = transaction.amount / len(transaction.debtors)
                for debtor in transaction.debtors:
                    if debtor != transaction.creditor:
                        debts[debtor][transaction.creditor] += amount_per_person

            total_payments_by_debtor: dict[str, float] = defaultdict(float)
            for payment in bill.payments:
                if payment.bill_id == bill.id:
                    total_payments_by_debtor[payment.person] += payment.amount

            for debtor in list(debts.keys()):
                if debtor in total_payments_by_debtor:
                    total_debt = sum(debts[debtor].values())
                    if total_debt > 0:
                        payment_remaining = total_payments_by_debtor[debtor]
                        for creditor in sorted(debts[debtor].keys()):
                            if payment_remaining <= 0:
                                break
                            debt_amount = debts[debtor][creditor]
                            if debt_amount > 0:
                                reduction = min(debt_amount, payment_remaining)
                                debts[debtor][creditor] -= reduction
                                payment_remaining -= reduction

            bill.optimizations = optimize_debts(debts)
            await self.repository.save()

        report = format_bill_report(bill, self.repository.db.details_infos)
        chunks = split_long_message(report)
        for i, chunk in enumerate(chunks):
            parse_mode = "Markdown" if is_valid_markdown(chunk) else None
            if i == 0:
                await context.message.reply_text(chunk, parse_mode=parse_mode)
            else:
                await context.message.chat.send_message(chunk, parse_mode=parse_mode)
        return True

    def help(self):
        return None


class BillEditHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                QuestionStep(
                    "transactions_text",
                    lambda ctx: f"Текущие транзакции:\n```\n{format_transactions_for_edit(ctx['bill'].transactions)}\n```\n\nВведите новые транзакции в том же формате (они полностью заменят старые):",
                    filter_answer=validate_message_text(
                        [
                            try_get(
                                lambda t: parse_transactions(t),
                                "Ошибка парсинга транзакций. Проверьте формат.",
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
        if len(parts) < 2:
            return False

        identifier = None
        if len(parts) >= 3 and parts[1] == "edit":
            identifier = parts[2]
        elif len(parts) >= 3 and parts[2] == "edit":
            identifier = parts[1]
        else:
            return False

        if identifier is None:
            return False

        bill = None
        try:
            bill_id = int(identifier)
            bill = next((b for b in self.repository.db.bills if b.id == bill_id), None)
        except ValueError:
            bill = next(
                (b for b in self.repository.db.bills if b.name == identifier), None
            )

        if bill is None:
            return False

        session_context["bill"] = bill
        return True

    async def on_session_finished(self, update, session_context):
        bill = session_context["bill"]
        bill.transactions = session_context["transactions_text"]

        debts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for transaction in bill.transactions:
            amount_per_person = transaction.amount / len(transaction.debtors)
            for debtor in transaction.debtors:
                if debtor != transaction.creditor:
                    debts[debtor][transaction.creditor] += amount_per_person

        total_payments_by_debtor: dict[str, float] = defaultdict(float)
        for payment in bill.payments:
            if payment.bill_id == bill.id:
                total_payments_by_debtor[payment.person] += payment.amount

        for debtor in list(debts.keys()):
            if debtor in total_payments_by_debtor:
                total_debt = sum(debts[debtor].values())
                if total_debt > 0:
                    payment_remaining = total_payments_by_debtor[debtor]
                    for creditor in sorted(debts[debtor].keys()):
                        if payment_remaining <= 0:
                            break
                        debt_amount = debts[debtor][creditor]
                        if debt_amount > 0:
                            reduction = min(debt_amount, payment_remaining)
                            debts[debtor][creditor] -= reduction
                            payment_remaining -= reduction

        bill.optimizations = optimize_debts(debts)
        await self.repository.save()

        report = format_bill_report(bill, self.repository.db.details_infos)
        chunks = split_long_message(report)
        for chunk in chunks:
            parse_mode = "Markdown" if is_valid_markdown(chunk) else None
            await get_message(update).chat.send_message(chunk, parse_mode=parse_mode)

    def help(self):
        return None


class BillCloseHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "bill"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 3 or parts[1] != "close":
            return False

        identifier = parts[2]

        bill = None
        try:
            bill_id = int(identifier)
            bill = next((b for b in self.repository.db.bills if b.id == bill_id), None)
        except ValueError:
            bill = next(
                (b for b in self.repository.db.bills if b.name == identifier), None
            )

        if bill is None:
            await context.message.reply_text(f"Счет '{identifier}' не найден")
            return True

        self.repository.db.bills.remove(bill)
        await self.repository.save()

        await context.message.reply_text(
            f"Счет '{bill.name}' (ID: {bill.id}) удален из базы данных"
        )
        return True

    def help(self):
        return None


@CommandHandler("bill", r"person\s+(?P<name>.+)")
class BillPersonHandler(Handler):
    async def chat(self, context: ChatBotContext, name: str):
        person_name = name.strip()

        total_debts: dict[str, float] = defaultdict(float)
        total_owed: dict[str, float] = defaultdict(float)

        for bill in self.repository.db.bills:
            for opt in bill.optimizations:
                if opt.debtor == person_name:
                    total_debts[opt.creditor] += opt.amount
                if opt.creditor == person_name:
                    total_owed[opt.debtor] += opt.amount

        lines = [f"👤 Статистика для: {person_name}", ""]

        if total_debts:
            lines.append("💸 Должен:")
            lines.append("```")
            lines.append(f"{'Кому':<18} {'Сумма':<12}")
            lines.append("-" * 30)
            for creditor, amount in sorted(
                total_debts.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"{creditor[:16]:<18} {amount:<12.2f}")
            lines.append("```")
            lines.append("")

        if total_owed:
            lines.append("💰 Должны:")
            lines.append("```")
            lines.append(f"{'Кто':<18} {'Сумма':<12}")
            lines.append("-" * 30)
            for debtor, amount in sorted(
                total_owed.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"{debtor[:16]:<18} {amount:<12.2f}")
            lines.append("```")
            lines.append("")

        if not total_debts and not total_owed:
            lines.append("Нет долгов")

        await context.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return True

    def help(self):
        return None


class BillPayHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                KeyboardStep(
                    "confirm",
                    lambda ctx: self._format_confirmation(ctx),
                    [
                        [
                            ("✅ Подтвердить", "confirm_yes", True),
                            ("❌ Отменить", "confirm_no", False),
                        ]
                    ],
                ),
            ]
        )
        self._pending_session_data = None

    async def chat(self, context):
        if not validate_command_msg(context.update, "bill"):
            return False

        assert context.message.text
        text = context.message.text.strip()
        parts = text.split()
        if len(parts) < 3 or parts[1] != "pay":
            return False

        bill_identifier = parts[2] if len(parts) > 2 else None
        if bill_identifier is None:
            await context.message.reply_text("Укажите ID или имя счета")
            return True

        bill = None
        try:
            bill_id_int = int(bill_identifier)
            bill = next(
                (b for b in self.repository.db.bills if b.id == bill_id_int), None
            )
        except ValueError:
            bill = next(
                (b for b in self.repository.db.bills if b.name == bill_identifier), None
            )

        if bill is None:
            await context.message.reply_text(f"Счет '{bill_identifier}' не найден")
            return True

        if len(parts) < 4:
            await context.message.reply_text("Укажите, кто должен")
            return True

        debtor = parts[3].strip()

        creditor = None
        amount_str = None

        if len(parts) > 4:
            next_part = parts[4].strip()
            next_part_lower = next_part.lower()
            if next_part_lower not in ["все", "all", ""]:
                try:
                    float(next_part)
                    amount_str = next_part
                except ValueError:
                    creditor = next_part
                    if len(parts) > 5:
                        amount_str = parts[5].strip()

        amount = None
        if amount_str:
            try:
                amount = float(amount_str)
            except ValueError:
                await context.message.reply_text(f"Неверная сумма: {amount_str}")
                return True

        relevant_opts = [opt for opt in bill.optimizations if opt.debtor == debtor]
        if creditor:
            relevant_opts = [opt for opt in relevant_opts if opt.creditor == creditor]

        if not relevant_opts:
            if creditor:
                await context.message.reply_text(
                    f"Не найдено оптимизаций для '{debtor}' -> '{creditor}' в счете '{bill.name}'"
                )
            else:
                await context.message.reply_text(
                    f"Не найдено оптимизаций для '{debtor}' в счете '{bill.name}'"
                )
            return True

        total_debt = sum(opt.amount for opt in relevant_opts)
        if creditor:
            total_paid = sum(
                p.amount
                for p in bill.payments
                if p.bill_id == bill.id
                and p.person == debtor
                and p.creditor == creditor
            )
        else:
            total_paid = sum(
                p.amount
                for p in bill.payments
                if p.bill_id == bill.id and p.person == debtor
            )
        remaining_debt = total_debt - total_paid

        if amount is None:
            payment_amount = remaining_debt
        else:
            payment_amount = amount

        if payment_amount <= 0:
            await context.message.reply_text("Сумма должна быть больше нуля")
            return True

        if payment_amount > remaining_debt + 0.01:
            await context.message.reply_text(
                f"Сумма превышает долг. Остаток долга: {remaining_debt:.2f}"
            )
            return True

        self._pending_session_data = {
            "bill": bill,
            "debtor": debtor,
            "creditor": creditor,
            "amount": amount_str,
        }
        return await super().chat(context)

    def _format_confirmation(self, ctx: dict) -> str:
        bill = ctx["bill"]
        debtor = ctx["debtor"]
        creditor = ctx.get("creditor")
        amount = ctx.get("amount")

        relevant_opts = [opt for opt in bill.optimizations if opt.debtor == debtor]
        if creditor:
            relevant_opts = [opt for opt in relevant_opts if opt.creditor == creditor]

        total_debt = sum(opt.amount for opt in relevant_opts)
        if creditor:
            total_paid = sum(
                p.amount
                for p in bill.payments
                if p.bill_id == bill.id
                and p.person == debtor
                and p.creditor == creditor
            )
        else:
            total_paid = sum(
                p.amount
                for p in bill.payments
                if p.bill_id == bill.id and p.person == debtor
            )
        remaining_debt = total_debt - total_paid

        if amount is None:
            payment_amount = remaining_debt
        else:
            payment_amount = float(amount)

        lines = ["💳 Подтверждение платежа", ""]
        lines.append(f"Счет: {bill.name} (ID: {bill.id})")
        lines.append(f"Кто должен: {debtor}")
        if creditor:
            lines.append(f"Кому должен: {creditor}")
        else:
            lines.append("Кому должен: всем")
        lines.append(f"Сумма: {payment_amount:.2f}")
        lines.append("")

        if creditor:
            opt = next((opt for opt in relevant_opts if opt.creditor == creditor), None)
            if opt:
                lines.append(f"Долг по оптимизации: {opt.amount:.2f}")
        else:
            lines.append(f"Общий долг по оптимизациям: {total_debt:.2f}")
            lines.append(f"Уже заплачено: {total_paid:.2f}")
            lines.append(f"Остаток: {remaining_debt:.2f}")

        return "\n".join(lines)

    def try_activate_session(self, update, session_context):
        if self._pending_session_data:
            session_context.update(self._pending_session_data)
            self._pending_session_data = None
            return True
        return False

    async def on_session_finished(self, update, session_context):
        if not session_context.get("confirm", False):
            await get_message(update).chat.send_message("Платеж отменен")
            return

        bill = session_context["bill"]
        debtor = session_context["debtor"]
        creditor = session_context.get("creditor")
        amount_str = session_context.get("amount")

        relevant_opts = [opt for opt in bill.optimizations if opt.debtor == debtor]
        if creditor:
            relevant_opts = [opt for opt in relevant_opts if opt.creditor == creditor]

        total_debt = sum(opt.amount for opt in relevant_opts)
        if creditor:
            total_paid = sum(
                p.amount
                for p in bill.payments
                if p.bill_id == bill.id
                and p.person == debtor
                and p.creditor == creditor
            )
        else:
            total_paid = sum(
                p.amount
                for p in bill.payments
                if p.bill_id == bill.id and p.person == debtor
            )
        remaining_debt = total_debt - total_paid

        if amount_str is None:
            payment_amount = remaining_debt
        else:
            payment_amount = float(amount_str)

        if creditor:
            payment = Payment(
                bill_id=bill.id,
                person=debtor,
                amount=payment_amount,
                creditor=creditor,
            )
            bill.payments.append(payment)
            await get_message(update).chat.send_message(
                f"✅ Платеж зарегистрирован: {debtor} заплатил {payment_amount:.2f} {creditor}"
            )
        else:
            payment_remaining = payment_amount

            payments_created = []
            for opt in sorted(relevant_opts, key=lambda x: x.creditor):
                if payment_remaining <= 0.01:
                    break

                already_paid_for_this_creditor = sum(
                    p.amount
                    for p in bill.payments
                    if p.bill_id == bill.id
                    and p.person == debtor
                    and p.creditor == opt.creditor
                )
                opt_remaining = opt.amount - already_paid_for_this_creditor

                if opt_remaining > 0.01:
                    opt_payment = min(opt_remaining, payment_remaining)
                    payment = Payment(
                        bill_id=bill.id,
                        person=debtor,
                        amount=opt_payment,
                        creditor=opt.creditor,
                    )
                    bill.payments.append(payment)
                    payments_created.append((opt.creditor, opt_payment))
                    payment_remaining -= opt_payment

            if payments_created:
                payments_info = ", ".join([f"{amt:.2f} {cred}" for cred, amt in payments_created])
                await get_message(update).chat.send_message(
                    f"✅ Платежи зарегистрированы: {debtor} заплатил {payments_info}"
                )
            else:
                await get_message(update).chat.send_message(
                    f"✅ Платеж зарегистрирован: {debtor} заплатил {payment_amount:.2f}"
                )

        await self.repository.save()

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
                        [
                            check(
                                lambda t: len(t.strip()) > 0, "Имя не может быть пустым"
                            )
                        ]
                    ),
                ),
                QuestionStep(
                    "description",
                    "Введите описание способов перевода денег:",
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
        if len(parts) < 3 or parts[1] != "details" or parts[2] != "add":
            return False

        return True

    async def on_session_finished(self, update, session_context):
        details_info = DetailsInfo(
            name=session_context["name"].strip(),
            description=session_context["description"].strip(),
        )

        existing = next(
            (
                p
                for p in self.repository.db.details_infos
                if p.name == details_info.name
            ),
            None,
        )
        if existing:
            existing.description = details_info.description
        else:
            self.repository.db.details_infos.append(details_info)

        await self.repository.save()
        await get_message(update).chat.send_message(
            f"Платежные данные для '{details_info.name}' сохранены"
        )

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
            (p for p in self.repository.db.details_infos if p.name == name), None
        )

        if details_info is None:
            return False

        session_context["details_info"] = details_info
        return True

    async def on_session_finished(self, update, session_context):
        details_info = session_context["details_info"]
        details_info.description = session_context["description"].strip()
        await self.repository.save()

        await get_message(update).chat.send_message(
            f"Платежные данные для '{details_info.name}' обновлены"
        )

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

        help_text = """📋 Помощь по команде /bill

/bill - посмотреть все счета
/bill add - добавить новый счет
/bill {id}/{name} - посмотреть отчет по счету
/bill {id}/{name} edit - изменить транзакции в счете
/bill edit {id}/{name} - изменить транзакции в счете
/bill close {id}/{name} - удалить счет из базы данных
/bill person {name} - статистика по человеку
/bill pay {bill id/name} {кто должен} [кому должен] [сколько] - зарегистрировать платеж
/bill details add - добавить платежные данные
/bill details edit {name} - изменить платежные данные

Формат транзакций при добавлении/редактировании:
наименование товара|сумма|кто должен(через запятую)|кому должны
Каждая транзакция с новой строки"""

        await context.message.reply_text(help_text)
        return True

    def help(self):
        return "/bill help - помощь по команде /bill"
