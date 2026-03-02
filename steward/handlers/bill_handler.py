import asyncio
import base64
import logging
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Callable
from typing import cast
from urllib.parse import urlparse

import httpx
from elevenlabs.client import ElevenLabs
from elevenlabs.types import SpeechToTextChunkResponseModel
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import CallbackBotContext, ChatBotContext
from steward.data.models.bill import Bill, DetailsInfo, Payment, Transaction
from steward.handlers.handler import Handler
from steward.helpers.ai import BILL_OCR_PROMPT, make_yandex_ai_query
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.google_drive import (
    find_files_in_folder_by_name,
    find_file_in_folder,
    get_file_link,
    insert_rows_into_sheet,
    read_spreadsheet_values,
    read_spreadsheet_values_from_sheet,
    rename_file,
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
from steward.helpers.transcription import build_named_speakers_text
from steward.helpers.validation import check, validate_message_text
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.session_registry import get_session_key
from steward.session.step import Step
from steward.session.steps.question_step import QuestionStep

logger = logging.getLogger(__name__)

FINANCES_FOLDER_ID = "1_YgOgjiqOyMZ1_jVAND_7HG9GfE7MpHX"
BILL_MAIN_SHEET_NAME = "Общее"
BILL_DATA_SHEET_NAME = "Данные"
BILL_DATA_SHEET_NAME_FALLBACK = "данные"
BILL_TEMPLATE_FILE_NAME = "Копия Шаблон"

_BILL_OCR_KB = "bill_ocr"
_BILL_OCR_NO_KB = "bill_ocr_no"
_BILL_OCR_STOP_KB = "bill_ocr_stop"

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
    debts: dict[str, dict[str, float]],
    payments: list[Payment],
    *,
    clamp_zero: bool = False,
) -> dict[str, dict[str, float]]:
    for p in payments:
        if not p.creditor:
            continue
        if p.person in debts and p.creditor in debts[p.person]:
            debts[p.person][p.creditor] -= p.amount
            if clamp_zero and debts[p.person][p.creditor] < 0:
                debts[p.person][p.creditor] = 0
    return debts


def _payments_to_remove_for_closed(
    debts_closed: dict[str, dict[str, float]],
    payments: list[Payment],
) -> tuple[list[Payment], list[tuple[Payment, float]]]:
    to_remove: list[Payment] = []
    to_reduce: list[tuple[Payment, float]] = []
    remaining: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for debtor, creds in debts_closed.items():
        for creditor, amount in creds.items():
            remaining[debtor][creditor] = amount
    for p in sorted(payments, key=lambda x: x.timestamp):
        if not p.creditor:
            continue
        debt = remaining.get(p.person, {}).get(p.creditor, 0)
        if debt < 0.01:
            continue
        if p.amount <= debt + 0.01:
            to_remove.append(p)
            remaining[p.person][p.creditor] -= p.amount
        else:
            new_amount = round(p.amount - debt, 2)
            if new_amount < 0.01:
                to_remove.append(p)
            else:
                to_reduce.append((p, new_amount))
            remaining[p.person][p.creditor] = 0
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
    debts_closed = apply_payments(debts_closed, payments, clamp_zero=True)
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
    rows = read_spreadsheet_values_from_sheet(file_id, BILL_MAIN_SHEET_NAME)
    if rows is None:
        rows = read_spreadsheet_values(file_id)
    return rows or []


def _read_bill_people_places_rows(file_id: str) -> list[list[str]]:
    rows = read_spreadsheet_values_from_sheet(file_id, BILL_DATA_SHEET_NAME)
    if rows is None:
        rows = read_spreadsheet_values_from_sheet(file_id, BILL_DATA_SHEET_NAME_FALLBACK)
    return rows or []


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def _parse_people_places(rows: list[list[str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        if not row:
            continue
        person = (row[0] if len(row) > 0 else "").strip()
        place = (row[1] if len(row) > 1 else "").strip()
        if not person:
            continue
        if _normalize_name(person) in {"персонаж", "действующее лицо"}:
            continue
        result[person] = place
    return result


def _build_people_places_prompt_block(people_places: dict[str, str]) -> str:
    if not people_places:
        return "персонаж | места\n(пока пусто)"
    lines = ["персонаж | места"]
    for person, place in sorted(people_places.items(), key=lambda x: _normalize_name(x[0])):
        lines.append(f"{person} | {place}")
    return "\n".join(lines)


def _build_bill_ai_input(context_text: str, people_places: dict[str, str]) -> str:
    return (
        "КОНТЕКСТ ДЛЯ РАЗБОРА:\n"
        f"{context_text}\n\n"
        "ТЕКУЩАЯ ТАБЛИЦА ЛИСТА 'данные':\n"
        f"{_build_people_places_prompt_block(people_places)}"
    )


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


def _build_bill_context_start_keyboard(file_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🧾 Добавить контекст",
                    callback_data=f"{_BILL_OCR_KB}|{file_id}",
                ),
                InlineKeyboardButton("Нет", callback_data=f"{_BILL_OCR_NO_KB}|"),
            ]
        ]
    )


def _build_bill_context_stop_keyboard(file_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⏹ Стоп",
                    callback_data=f"{_BILL_OCR_STOP_KB}|{file_id}",
                )
            ]
        ]
    )


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


def _escape_md(text: str) -> str:
    return (
        text.replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def _format_bill_page(ctx: PageFormatContext[Bill]) -> str:
    from steward.helpers.formats import format_lined_list

    if not ctx.data:
        return "Нет счетов"
    items = []
    for bill in ctx.data:
        link = get_file_link(bill.file_id)
        name = _escape_md(bill.name)
        if link:
            name = f"[{name}]({link})"
        items.append((bill.id, name))
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

    async def chat(self, context):
        key = get_session_key(context.update)
        if key not in self.sessions and validate_command_msg(context.update, "bill"):
            assert context.message.text
            parts = context.message.text.split(maxsplit=2)
            if len(parts) >= 3 and parts[1] == "add":
                name = parts[2].strip()
                if name:
                    await self.on_session_finished(context.update, {"name": name})
                    return True
        return await super().chat(context)

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
            templates = find_files_in_folder_by_name(folder_id, BILL_TEMPLATE_FILE_NAME)
            if not templates:
                await get_message(update).chat.send_message(
                    f"Файл '{name}' не найден, и шаблон '{BILL_TEMPLATE_FILE_NAME}' отсутствует в папке «финансы»."
                )
                return
            template_file_id = templates[0]
            renamed_file_id, error = rename_file(template_file_id, name)
            if not renamed_file_id:
                await get_message(update).chat.send_message(
                    f"Не удалось переименовать шаблон в '{name}': {error or 'неизвестная ошибка'}"
                )
                return
            file_id = renamed_file_id
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
        ocr_keyboard = _build_bill_context_start_keyboard(file_id)
        chunks = split_long_message(msg)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            parse_mode = "Markdown" if is_valid_markdown(chunk) else None
            markup = ocr_keyboard if is_last else None
            await get_message(update).chat.send_message(
                chunk, parse_mode=parse_mode, reply_markup=markup
            )

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
            "edit",
            "pay",
            "details",
            "help",
            "report",
            "close",
            "debug",
            "force",
        ):
            return False
        if len(parts) >= 3 and parts[-1].lower() == "edit":
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
        debts_this = apply_payments(
            debts_this, self.repository.db.payments, clamp_zero=True
        )
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
        ocr_keyboard = _build_bill_context_start_keyboard(bill.file_id)
        chunks = split_long_message(report)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            markup = ocr_keyboard if is_last else None
            if i == 0:
                await context.message.reply_text(
                    chunk, parse_mode="Markdown", reply_markup=markup
                )
            else:
                await context.message.chat.send_message(
                    chunk, parse_mode="Markdown", reply_markup=markup
                )
        return True

    def help(self):
        return None


_BILL_NAV_KB = "bill_nav"


def _build_bill_nav_keyboard(
    bills: list[Bill],
    current: str,
) -> InlineKeyboardMarkup:
    sorted_bills = sorted(bills, key=lambda b: b.id)
    bill_ids = [str(b.id) for b in sorted_bills]

    def cb(target: str) -> str:
        prefix = "~" if target == current else ""
        return f"{_BILL_NAV_KB}|{prefix}{target}"

    if current == "общий":
        prev_target = bill_ids[-1] if bill_ids else "общий"
        next_target = bill_ids[0] if bill_ids else "общий"
    else:
        idx = bill_ids.index(current) if current in bill_ids else 0
        prev_target = bill_ids[idx - 1] if idx > 0 else "общий"
        next_target = bill_ids[idx + 1] if idx < len(bill_ids) - 1 else "общий"

    first_target = bill_ids[0] if bill_ids else "общий"
    last_target = bill_ids[-1] if bill_ids else "общий"

    общий_label = "• общий" if current == "общий" else "общий"

    row1 = [
        InlineKeyboardButton("<<", callback_data=cb(first_target)),
        InlineKeyboardButton("<", callback_data=cb(prev_target)),
        InlineKeyboardButton(общий_label, callback_data=cb("общий")),
        InlineKeyboardButton(">", callback_data=cb(next_target)),
        InlineKeyboardButton(">>", callback_data=cb(last_target)),
    ]

    last_5 = sorted_bills[-5:]
    row2 = [
        InlineKeyboardButton(
            f"• {b.id}" if str(b.id) == current else str(b.id),
            callback_data=cb(str(b.id)),
        )
        for b in last_5
    ]

    rows = [row1]
    if row2:
        rows.append(row2)
    return InlineKeyboardMarkup(rows)


def _generate_main_report_text(
    bills: list[Bill],
    payments: list[Payment],
    details_infos: list[DetailsInfo],
) -> str:
    all_tx = _load_all_transactions(bills)
    participants = _participants_from_transactions(all_tx)
    payments_relevant = _payments_relevant_to_participants(payments, participants)
    debts = debts_from_transactions(all_tx)
    debts = apply_payments(debts, payments)
    debts = _net_direct_debts(debts)
    debts_list = debts_to_list(debts)
    closable = [b.id for b in bills] if not debts_list else None
    return _format_report(
        debts_list,
        payments_relevant,
        details_infos,
        title="📋 Общий отчет",
        closable_bill_ids=closable,
    )


def _generate_single_bill_report_text(
    bill: Bill,
    all_bills: list[Bill],
    payments: list[Payment],
    details_infos: list[DetailsInfo],
) -> str:
    raw_rows = _read_bill_raw_rows(bill.file_id)
    transactions = parse_transactions_from_sheet(raw_rows[:-1] if raw_rows else [])
    all_tx = _load_all_transactions(all_bills)
    debts_this = debts_from_transactions(transactions)
    debts_this = apply_payments(debts_this, payments, clamp_zero=True)
    debts_this = _net_direct_debts(debts_this)
    debts_list_this = debts_to_list(debts_this)
    debts_all = debts_from_transactions(all_tx)
    debts_all = apply_payments(debts_all, payments)
    debts_all = _net_direct_debts(debts_all)
    debts_list_all = debts_to_list(debts_all)
    closable_this = [bill.id] if not debts_list_this else None
    closable_all = [b.id for b in all_bills] if not debts_list_all else None
    participants = _participants_from_transactions(transactions)
    payments_relevant = _payments_relevant_to_participants(payments, participants)
    return _format_report(
        debts_list_this,
        payments_relevant,
        details_infos,
        title=f"📋 Счет: {bill.name}",
        file_link=get_file_link(bill.file_id),
        closable_bill_ids=closable_this,
        debts_list_all=debts_list_all,
        closable_bill_ids_all=closable_all,
    )


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
        report = _generate_main_report_text(
            bills, self.repository.db.payments, self.repository.db.details_infos
        )
        keyboard = _build_bill_nav_keyboard(bills, "общий")
        chunks = split_long_message(report)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            markup = keyboard if is_last else None
            if i == 0:
                await context.message.reply_text(
                    chunk, parse_mode="Markdown", reply_markup=markup
                )
            else:
                await context.message.chat.send_message(
                    chunk, parse_mode="Markdown", reply_markup=markup
                )
        return True

    async def callback(self, context: CallbackBotContext):
        if not context.callback_query.data:
            return False
        data = context.callback_query.data
        if not data.startswith(f"{_BILL_NAV_KB}|"):
            return False
        target = data.split("|", 1)[1]
        if target.startswith("~"):
            await context.callback_query.answer()
            return True
        bills = self.repository.db.bills
        if not bills:
            await context.callback_query.answer("Нет счетов")
            return True
        if not google_drive_available():
            await context.callback_query.answer("Google Drive недоступен")
            return True
        if target == "общий":
            report = _generate_main_report_text(
                bills, self.repository.db.payments, self.repository.db.details_infos
            )
        else:
            try:
                bill_id = int(target)
            except ValueError:
                await context.callback_query.answer("Неверный ID")
                return True
            bill = next((b for b in bills if b.id == bill_id), None)
            if not bill:
                await context.callback_query.answer(f"Счет {target} не найден")
                return True
            report = _generate_single_bill_report_text(
                bill,
                bills,
                self.repository.db.payments,
                self.repository.db.details_infos,
            )
        keyboard = _build_bill_nav_keyboard(bills, target)
        chunks = split_long_message(report)
        text = chunks[0] if chunks else "Нет данных"
        parse_mode = "Markdown" if is_valid_markdown(text) else None
        await context.callback_query.message.edit_text(
            text=text, parse_mode=parse_mode, reply_markup=keyboard
        )
        await context.callback_query.answer()
        return True

    def help(self):
        return "/bill — основной отчёт по всем должникам"

    def prompt(self):
        return (
            "▶ /bill — управление счетами (расходы, долги, переводы)\n"
            "  Основной отчёт по всем должникам: /bill\n"
            "  Список всех счетов: /bill all\n"
            "  Отчёт по конкретному счету: /bill <id> или /bill <имя_счёта>\n"
            "  Добавить контекст в счёт: /bill <id> edit\n"
            "  Отчёт с отладкой: /bill <id> debug\n"
            "  Добавить новый счет: /bill add <имя> или /bill add (начинает сессию)\n"
            "  Если счёт не найден, будет переименован найденный шаблон 'Копия Шаблон' в папке финансов\n"
            "  Зарегистрировать перевод: /bill pay <кто> <кому> <сумма>\n"
            "  Удалить последние N платежей: /bill pay force delete <N> (только админ)\n"
            "  Закрыть счета: /bill close <id1> <id2> ...\n"
            "  Добавить платёжные данные: /bill details add <пользователь> <описание> или /bill details add <пользователь> (начинает сессию)\n"
            "  Изменить платёжные данные: /bill details edit <пользователь> <описание> или /bill details edit <пользователь> (начинает сессию)\n"
            "  Помощь по /bill: /bill help\n"
            "  Примеры:\n"
            "  - «покажи общий отчёт по счетам» → /bill\n"
            "  - «покажи все счета» → /bill all\n"
            "  - «покажи счёт 3» → /bill 3\n"
            "  - «добавь контекст в счёт 3» → /bill 3 edit\n"
            "  - «зарегистрируй перевод Вася → Петя 500» → /bill pay Вася Петя 500\n"
            "  - «закрой счёт 1 и 2» → /bill close 1 2\n"
            "  - «помощь по биллу» → /bill help\n"
            "  - «добавь счёт» → /bill add\n"
            "\n"
            "  ВОПРОСЫ О ДАННЫХ В КОНТЕКСТЕ:\n"
            "  Если в контексте уже есть отчёт с долгами и пользователь задаёт ВОПРОС\n"
            "  (сколько я должен, кто должен X, какие долги у Y, и т.п.),\n"
            "  НЕ возвращай /bill — верни пустой ответ. Данные уже есть в контексте.\n"
            "\n"
            "  ЗАКРЫТИЕ ДОЛГОВ ЧЕРЕЗ КОНТЕКСТ:\n"
            "  В контексте долги представлены в формате: «X должен Y: сумма».\n"
            "  Если пользователь говорит что кто-то «заплатил по долгам» / «никому не должен» / «рассчитался»,\n"
            "  найди все строки «X должен Y: сумма» где X — указанный человек,\n"
            "  и сгенерируй /bill pay X Y сумма для каждой.\n"
            "  Имя берётся из запроса, из «Отправитель» контекста, или по смыслу («чел» = Отправитель).\n"
            "  Строки где человек после «должен» (т.е. ему должны) — НЕ включай.\n"
            "\n"
            "  Пример:\n"
            "  Контекст:\n"
            "    Альфа должен Бета: 1000\n"
            "    Бета должен Гамма: 82.33\n"
            "    Бета должен Дельта: 65\n"
            "    Бета должен Эпсилон: 12\n"
            "  Запрос: «Бета заплатил по долгам»\n"
            "  Ответ:\n"
            "  /bill pay Бета Гамма 82.33\n"
            "  /bill pay Бета Дельта 65\n"
            "  /bill pay Бета Эпсилон 12\n"
            "  «Альфа должен Бета: 1000» НЕ включается — тут Альфа должен Бета, а не Бета кому-то"
        )


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

    async def chat(self, context):
        key = get_session_key(context.update)
        if key not in self.sessions and validate_command_msg(context.update, "bill"):
            assert context.message.text
            text = context.message.text
            lines = text.split("\n", 1)
            first_line_parts = lines[0].split(None, 3)

            if (
                len(first_line_parts) >= 4
                and first_line_parts[1] == "details"
                and first_line_parts[2] == "add"
            ):
                name = first_line_parts[3].strip()

                if len(lines) == 2:
                    description = lines[1].strip()
                    if name and description:
                        await self.on_session_finished(
                            context.update,
                            {"name": name, "description": description},
                        )
                        return True
                else:
                    parts_single = text.split(None, 4)
                    if len(parts_single) >= 5:
                        name_single = parts_single[3].strip()
                        description = parts_single[4].strip()
                        if name_single and description:
                            await self.on_session_finished(
                                context.update,
                                {"name": name_single, "description": description},
                            )
                            return True
        return await super().chat(context)

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

    async def chat(self, context):
        key = get_session_key(context.update)
        if key not in self.sessions and validate_command_msg(context.update, "bill"):
            assert context.message.text
            text = context.message.text
            lines = text.split("\n", 1)
            first_line_parts = lines[0].split()

            if (
                len(first_line_parts) >= 4
                and first_line_parts[1] == "details"
                and first_line_parts[2] == "edit"
            ):
                description = lines[1].strip() if len(lines) == 2 else None

                if not description and len(first_line_parts) >= 5:
                    for i in range(4, len(first_line_parts)):
                        candidate = " ".join(first_line_parts[3:i])
                        info = next(
                            (
                                d
                                for d in self.repository.db.details_infos
                                if d.name == candidate
                            ),
                            None,
                        )
                        if info is not None:
                            description = " ".join(first_line_parts[i:]).strip()
                            if description:
                                await self.on_session_finished(
                                    context.update,
                                    {"details_info": info, "description": description},
                                )
                                return True

                if description and len(first_line_parts) >= 4:
                    name = " ".join(first_line_parts[3:])
                    info = next(
                        (d for d in self.repository.db.details_infos if d.name == name),
                        None,
                    )
                    if info is not None:
                        await self.on_session_finished(
                            context.update,
                            {"details_info": info, "description": description},
                        )
                        return True
        return await super().chat(context)

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
        tx_closed = []
        for b in bills_to_close:
            tx_closed.extend(_load_bill_transactions(b.file_id))
        debts_closed = debts_from_transactions(tx_closed)
        debts_closed = _net_direct_debts(debts_closed)
        to_remove, to_reduce = _payments_to_remove_for_closed(
            debts_closed, self.repository.db.payments
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


async def _run_ffmpeg(*args: str):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"ffmpeg failed: {stderr.decode(errors='replace')}")


async def _read_voice_bytes(context, file_id: str) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    try:
        return bytes(await tg_file.download_as_bytearray())
    except Exception:
        file_path = tg_file.file_path
        if not file_path:
            raise
        if file_path.startswith("http://") or file_path.startswith("https://"):
            parsed = urlparse(file_path)
            path = parsed.path
            if path.startswith("/file/bot"):
                rel = path[len("/file/bot") :]
                first_slash = rel.find("/")
                file_path = rel[first_slash + 1 :] if first_slash > 0 else rel.lstrip("/")
            else:
                file_path = path.lstrip("/")
        local_path = Path(f"/data/{context.bot.token}/{file_path}")
        if not local_path.exists():
            raise
        return local_path.read_bytes()


async def _transcribe_voice_bytes(data: bytes) -> str | None:
    stt_key = os.environ.get("EVELEN_LABS_STT")
    if not stt_key:
        return None
    with tempfile.TemporaryDirectory(prefix="bill_voice_stt_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_audio = tmp_path / "voice.ogg"
        prepared_audio = tmp_path / "voice.mp3"
        source_audio.write_bytes(data)
        await _run_ffmpeg(
            "-i",
            str(source_audio),
            "-ac",
            "1",
            "-ar",
            "44100",
            str(prepared_audio),
        )
        with open(prepared_audio, "rb") as audio_file:
            client = ElevenLabs(
                api_key=stt_key,
                httpx_client=httpx.Client(
                    timeout=240,
                    proxy=os.environ.get("DOWNLOAD_PROXY"),
                ),
            )
            payload = audio_file.read()
            try:
                result = await asyncio.to_thread(
                    lambda: client.speech_to_text.convert(
                        file=payload,
                        model_id="scribe_v1",
                        tag_audio_events=True,
                        diarize=True,
                    )
                )
            except Exception as e:
                if "not found" not in str(e).lower():
                    raise
                result = await asyncio.to_thread(
                    lambda: client.speech_to_text.convert(
                        file=payload,
                        tag_audio_events=True,
                        diarize=True,
                    )
                )
        words = cast(SpeechToTextChunkResponseModel, result).words or []
        text_with_names = build_named_speakers_text(words)
        if text_with_names:
            return text_with_names
        text = getattr(result, "text", None)
        if isinstance(text, str):
            stripped = text.strip()
            if stripped:
                return stripped
    return None


class CollectBillContextStep(Step):
    def __init__(self):
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            context.session_context.setdefault("bill_context_parts", [])
            file_id = context.session_context.get("file_id", "")
            await context.message.reply_text(
                "Отправляйте контекст для счёта:\n"
                "• фото — распознаю текст с картинки\n"
                "• голосовые — расшифрую в текст\n\n"
                "Когда закончите, нажмите кнопку «Стоп».",
                reply_markup=_build_bill_context_stop_keyboard(file_id),
            )
            self.is_waiting = True
            return False

        text_parts: list[str] = context.session_context.setdefault("bill_context_parts", [])

        if context.message.photo:
            api_key = os.environ.get("AI_VISION_SECRET")
            folder_id = os.environ.get("YC_FOLDER_ID")
            if not api_key or not folder_id:
                await context.message.reply_text(
                    "Yandex OCR не настроен: задайте AI_VISION_SECRET и YC_FOLDER_ID"
                )
                return False

            photo = context.message.photo[-1]
            try:
                from steward.handlers.newtext_handler import _read_photo_bytes, _yandex_ocr

                data = await _read_photo_bytes(context, photo.file_id)
                content_b64 = base64.standard_b64encode(data).decode("ascii")
                mime = "JPEG"
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    mime = "PNG"
                text = await _yandex_ocr(content_b64, mime, api_key, folder_id)
            except httpx.HTTPStatusError as e:
                logger.exception("Yandex OCR HTTP error: %s", e)
                await context.message.reply_text(
                    f"Ошибка OCR API: {e.response.status_code}"
                )
                return False
            except Exception as e:
                logger.exception("Yandex OCR failed: %s", e)
                await context.message.reply_text(f"Не удалось распознать фото: {e}")
                return False

            if not text:
                await context.message.reply_text("Текст на картинке не найден")
                return False

            text_parts.append(f"[Фото]\n{text}")
            await context.message.reply_text("✅ Фото добавлено в контекст")
            return False

        if context.message.voice:
            try:
                voice_bytes = await _read_voice_bytes(context, context.message.voice.file_id)
                voice_text = await _transcribe_voice_bytes(voice_bytes)
            except Exception as e:
                logger.exception("Voice transcription failed: %s", e)
                await context.message.reply_text(f"Не удалось обработать голосовое: {e}")
                return False

            if not voice_text:
                await context.message.reply_text(
                    "Не удалось расшифровать голосовое. Проверьте EVELEN_LABS_STT."
                )
                return False

            text_parts.append(f"[Голосовое]\n{voice_text}")
            await context.message.reply_text("✅ Голосовое добавлено в контекст")
            return False

        if context.message.text and context.message.text.strip() and not context.message.text.startswith("/"):
            text_parts.append(f"[Текст]\n{context.message.text.strip()}")
            await context.message.reply_text("✅ Текст добавлен в контекст")
            return False

        await context.message.reply_text(
            "Поддерживаются фото, голосовые и текст. "
            "Когда закончите — нажмите кнопку «Стоп»."
        )
        return False

    async def callback(self, context):
        if not self.is_waiting:
            await context.callback_query.message.edit_reply_markup(reply_markup=None)
            await context.callback_query.answer()
            context.session_context.setdefault("bill_context_parts", [])
            file_id = context.session_context.get("file_id", "")
            await context.callback_query.message.chat.send_message(
                "Отправляйте контекст для счёта:\n"
                "• фото — распознаю текст с картинки\n"
                "• голосовые — расшифрую в текст\n\n"
                "Когда закончите, нажмите кнопку «Стоп».",
                reply_markup=_build_bill_context_stop_keyboard(file_id),
            )
            self.is_waiting = True
            return False

        data = context.callback_query.data or ""
        if not data.startswith(f"{_BILL_OCR_STOP_KB}|"):
            return False
        target_file_id = data.split("|", 1)[1]
        current_file_id = context.session_context.get("file_id", "")
        if target_file_id and current_file_id and target_file_id != current_file_id:
            await context.callback_query.answer("Эта кнопка не для текущей сессии")
            return True
        await context.callback_query.answer()
        try:
            await context.callback_query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("Could not clear stop keyboard", exc_info=True)
        self.is_waiting = False
        return True

    def stop(self):
        self.is_waiting = False


def _parse_ai_bill_response(text: str) -> tuple[list[list[str]], list[list[str]]]:
    main_rows: list[list[str]] = []
    data_rows: list[list[str]] = []
    section: str | None = None

    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = line.strip("[]").strip().lower().rstrip(":")
        if normalized == "общее":
            section = "main"
            continue
        if normalized == "данные":
            section = "data"
            continue

        if "|" not in line or section is None:
            continue

        parts = [p.strip() for p in line.split("|")]
        if section == "main":
            if len(parts) < 5:
                continue
            if _normalize_name(parts[0]) == "наименование":
                continue
            name = parts[0]
            amount_raw = parts[1]
            payers = parts[2]
            factual_payer = parts[3]
            source = parts[4]
            if not name or not payers or not factual_payer:
                continue
            try:
                amount = _parse_amount(amount_raw)
            except ValueError:
                continue
            amount_str = f"{amount:.2f}".replace(".", ",")
            main_rows.append([name, amount_str, payers, factual_payer, source])
            continue

        if section == "data":
            if len(parts) < 2:
                continue
            person = parts[0]
            place = parts[1]
            if not person or _normalize_name(person) == "персонаж":
                continue
            data_rows.append([person, place])

    return main_rows, data_rows


def _build_new_people_rows(
    existing_people_places: dict[str, str], ai_data_rows: list[list[str]]
) -> list[list[str]]:
    existing_names = {_normalize_name(name) for name in existing_people_places}
    seen_new: set[str] = set()
    out: list[list[str]] = []
    for row in ai_data_rows:
        person = (row[0] if len(row) > 0 else "").strip()
        place = (row[1] if len(row) > 1 else "").strip()
        norm = _normalize_name(person)
        if not norm or norm in existing_names or norm in seen_new:
            continue
        out.append([person, place])
        seen_new.add(norm)
    return out


class BillOcrHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__([CollectBillContextStep()])

    def _find_bill_by_identifier(self, identifier: str) -> Bill | None:
        try:
            bill_id = int(identifier)
            return next((b for b in self.repository.db.bills if b.id == bill_id), None)
        except ValueError:
            return next(
                (
                    b
                    for b in self.repository.db.bills
                    if b.name.lower() == identifier.lower()
                ),
                None,
            )

    async def chat(self, context):
        key = get_session_key(context.update)
        if key not in self.sessions and validate_command_msg(context.update, "bill"):
            assert context.message.text
            parts = context.message.text.split()
            if len(parts) >= 3 and parts[-1].lower() == "edit":
                if not google_drive_available():
                    await context.message.reply_text("Google Drive недоступен")
                    return True
                identifier = " ".join(parts[1:-1]).strip()
                if not identifier:
                    await context.message.reply_text("Использование: /bill {id} edit")
                    return True
                bill = self._find_bill_by_identifier(identifier)
                if bill is None:
                    await context.message.reply_text(f"Счет '{identifier}' не найден")
                    return True
        return await super().chat(context)

    def try_activate_session(self, update, session_context):
        if not update.callback_query or not update.callback_query.data:
            if not validate_command_msg(update, "bill"):
                return False
            assert update.message and update.message.text
            parts = update.message.text.split()
            if len(parts) < 3 or parts[-1].lower() != "edit":
                return False
            identifier = " ".join(parts[1:-1]).strip()
            if not identifier:
                return False
            bill = self._find_bill_by_identifier(identifier)
            if bill is None:
                return False
            session_context["file_id"] = bill.file_id
            return True
        data = update.callback_query.data
        if not data.startswith(f"{_BILL_OCR_KB}|"):
            return False
        file_id = data.split("|", 1)[1]
        if not file_id:
            return False
        session_context["file_id"] = file_id
        return True

    async def callback(self, context):
        if context.callback_query and context.callback_query.data:
            data = context.callback_query.data
            if data.startswith(f"{_BILL_OCR_NO_KB}|"):
                await context.callback_query.message.edit_reply_markup(
                    reply_markup=None
                )
                await context.callback_query.answer()
                return True
        return await super().callback(context)

    async def on_session_finished(self, update, session_context):
        text_parts: list[str] = session_context.get("bill_context_parts", [])
        ocr_text = "\n\n".join(text_parts).strip()
        file_id = session_context.get("file_id")
        msg = get_message(update)

        if not ocr_text:
            await msg.chat.send_message("Контекст пуст. Нечего добавлять в счёт.")
            return
        if len(ocr_text) > 15000:
            ocr_text = ocr_text[:15000]
            await msg.chat.send_message(
                "Контекст был слишком длинным, отправил в нейронку первые 15000 символов."
            )
        if not file_id:
            await msg.chat.send_message("Не найден файл счёта")
            return

        people_places_rows = _read_bill_people_places_rows(file_id)
        people_places = _parse_people_places(people_places_rows)
        ai_input = _build_bill_ai_input(ocr_text, people_places)

        try:
            ai_response = await make_yandex_ai_query(
                get_message(update).chat.id,
                [("user", ai_input)],
                BILL_OCR_PROMPT,
            )
        except Exception as e:
            logger.exception("AI request failed: %s", e)
            await msg.chat.send_message(f"Ошибка AI: {e}")
            return

        rows, ai_data_rows = _parse_ai_bill_response(ai_response)
        if not rows:
            await msg.chat.send_message(
                f"Не удалось разобрать ответ AI:\n{ai_response}"
            )
            return

        if not insert_rows_into_sheet(file_id, rows, BILL_MAIN_SHEET_NAME):
            await msg.chat.send_message("Не удалось записать данные в таблицу")
            return

        new_people_rows = _build_new_people_rows(people_places, ai_data_rows)
        data_inserted = 0
        if new_people_rows:
            if insert_rows_into_sheet(file_id, new_people_rows, BILL_DATA_SHEET_NAME) or insert_rows_into_sheet(
                file_id,
                new_people_rows,
                BILL_DATA_SHEET_NAME_FALLBACK,
            ):
                data_inserted = len(new_people_rows)
            else:
                await msg.chat.send_message(
                    "⚠️ Расходы добавлены, но не удалось обновить лист 'данные'."
                )

        lines = [f"✅ Добавлено {len(rows)} строк в счёт:"]
        for r in rows:
            lines.append(f"• {r[0]} — {r[1]}")
        if data_inserted > 0:
            lines.append("")
            lines.append(f"🧩 Добавлено {data_inserted} новых участников в лист 'данные'")
        await msg.chat.send_message("\n".join(lines))

    async def on_stop(self, update, session_context):
        await get_message(update).chat.send_message("Сбор контекста отменён")

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

/bill — общий отчет по всем счетам
/bill all — список всех счетов
/bill {id} — отчет по счету (+ кнопка «Добавить контекст»)
/bill {id} edit — собрать контекст и добавить в счёт (не перезаписывает)
/bill {id} debug — отчет по счету с выводом сырых данных из таблицы
/bill add — добавить счет (если файла нет, переименовывается найденный «Копия Шаблон»)
/bill pay {кто} {кому} {сумма} — зарегистрировать перевод
/bill pay force delete {count} — удалить последние N платежей (админ)
/bill close {id1} {id2} ... — закрыть счета
/bill details add {пользователь} — добавить платежные данные
/bill details edit {пользователь} — изменить платежные данные"""
        await context.message.reply_text(help_text)
        return True

    def help(self):
        return "/bill help — помощь по /bill"
