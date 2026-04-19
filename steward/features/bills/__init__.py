from steward.data.models.bill import Bill, DetailsInfo, Payment
from steward.features.bills.ocr_session import (
    CollectBillContextStep,
    build_bill_context_start_keyboard,
    finalize_ocr,
)
from steward.features.bills.payments import (
    apply_close,
    bills_closable,
    debts_from_transactions,
    debts_to_list,
    net_direct_debts,
    parse_bill_ids,
)
from steward.features.bills.reports import (
    format_bill_page,
    format_report,
    generate_main_report_text,
    generate_single_bill_report_text,
    report_for_target,
)
from steward.features.bills.sheets import (
    BILL_TEMPLATE_FILE_NAME,
    format_debug_rows,
    get_bills_folder_id,
    load_bill_transactions,
    parse_transactions_from_sheet,
    read_bill_raw_rows,
)
from steward.features.bills.texts import (
    HELP_TEXT,
    PROMPT_TEXT,
    build_bill_nav_keyboard,
    split_inline_details,
    split_inline_details_edit,
)
from steward.framework import (
    Feature,
    FeatureContext,
    ask,
    collection,
    on_callback,
    paginated,
    step,
    subcommand,
    wizard,
)
from steward.helpers.google_drive import (
    find_file_in_folder,
    find_files_in_folder_by_name,
    get_file_link,
)
from steward.helpers.google_drive import is_available as google_drive_available
from steward.helpers.google_drive import rename_file
from steward.helpers.tg_update_helpers import (
    get_message,
    is_valid_markdown,
    split_long_message,
)
from steward.helpers.validation import check, validate_message_text


class BillsFeature(Feature):
    command = "bill"
    description = "Управление счетами (расходы, долги, переводы)"
    custom_help = HELP_TEXT
    custom_prompt = PROMPT_TEXT

    bills = collection("bills")
    payments = collection("payments")
    details_infos = collection("details_infos")

    @subcommand("", description="Общий отчёт по счетам")
    async def main_report(self, ctx: FeatureContext):
        await self._send_main_report(ctx)

    @subcommand("report", description="Общий отчёт по счетам")
    async def main_report_alias(self, ctx: FeatureContext):
        await self._send_main_report(ctx)

    @subcommand("all", description="Список всех счетов")
    async def list_all(self, ctx: FeatureContext):
        if not self.bills.all():
            await ctx.reply("Нет счетов")
            return
        await self.paginate(ctx, "bills")

    @subcommand("help", description="Помощь по /bill")
    async def show_help(self, ctx: FeatureContext):
        await ctx.reply(HELP_TEXT, markdown=False)

    @subcommand("add", description="Добавить счёт (сессия)")
    async def add_session(self, ctx: FeatureContext):
        await self.start_wizard("bill:add", ctx)

    @subcommand("add <name:rest>", description="Добавить счёт по имени")
    async def add_with_name(self, ctx: FeatureContext, name: str):
        name = name.strip()
        if not name:
            await ctx.reply("Имя не может быть пустым")
            return
        await self._add_bill(ctx, name)

    @subcommand("close <ids:rest>", description="Закрыть счета")
    async def close(self, ctx: FeatureContext, ids: str):
        if not google_drive_available():
            await ctx.reply("Google Drive недоступен")
            return
        bill_ids = parse_bill_ids(ids)
        if bill_ids is None:
            await ctx.reply("Неверный формат. Используйте: /bill close {id1} {id2} ...")
            return
        if not bill_ids:
            await ctx.reply("Укажите ID счетов для закрытия: /bill close {id1} {id2} ...")
            return
        bills = self.bills.all()
        bills_to_close = [b for b in bills if b.id in bill_ids]
        if len(bills_to_close) != len(bill_ids):
            missing = set(bill_ids) - {b.id for b in bills_to_close}
            await ctx.reply(
                f"Счета не найдены: {', '.join(str(i) for i in sorted(missing))}"
            )
            return
        payments = list(self.payments)
        if not bills_closable(bill_ids, bills, load_bill_transactions, payments):
            await ctx.reply(
                "Закрытие невозможно: не все должники совершили переводы "
                "или остаются непогашенные долги. Проверьте отчёт по счёту."
            )
            return
        to_remove, to_reduce = apply_close(
            bills_to_close, payments, load_bill_transactions
        )
        for p in to_remove:
            self.payments.remove(p)
        for p, new_amount in to_reduce:
            p.amount = new_amount
        for b in bills_to_close:
            self.bills.remove(b)
        await self.bills.save()
        names = ", ".join(b.name for b in bills_to_close)
        await ctx.reply(f"✅ Счета закрыты: {names}")

    @subcommand(
        "pay force delete <count:int>",
        description="Удалить последние N платежей",
        admin=True,
    )
    async def pay_force_delete(self, ctx: FeatureContext, count: int):
        if count <= 0:
            await ctx.reply("Количество должно быть больше 0")
            return
        payments = list(self.payments)
        if count > len(payments):
            count = len(payments)
        if count == 0:
            await ctx.reply("Нет платежей для удаления")
            return
        deleted = payments[-count:]
        for p in deleted:
            self.payments.remove(p)
        await self.payments.save()
        lines = [f"🗑 Удалено {len(deleted)} платежей:"]
        for p in deleted:
            cred = p.creditor or "—"
            date_str = p.timestamp.strftime("%Y-%m-%d %H:%M")
            lines.append(f"• {p.person} → {cred} {p.amount:.2f} ({date_str})")
        await ctx.reply("\n".join(lines))

    @subcommand(
        "pay <person:str> <creditor:str> <amount:float>",
        description="Зарегистрировать перевод",
    )
    async def pay(self, ctx: FeatureContext, person: str, creditor: str, amount: float):
        if amount <= 0:
            await ctx.reply("Сумма должна быть больше 0")
            return
        p = Payment(person=person.strip(), amount=amount, creditor=creditor.strip())
        self.payments.add(p)
        await self.payments.save()
        await ctx.reply(f"✅ Платеж: {person} → {creditor} {amount:.2f}")

    @subcommand("details add <name:rest>", description="Добавить/обновить платёжные данные")
    async def details_add(self, ctx: FeatureContext, name: str):
        text = ctx.message.text if ctx.message else ""
        inline = split_inline_details(text)
        if inline is not None:
            await self._save_details(ctx, *inline)
            return
        clean_name = name.split("\n", 1)[0].strip()
        if not clean_name:
            await ctx.reply("Укажите имя пользователя")
            return
        await self.start_wizard("bill:details_add", ctx, name=clean_name)

    @subcommand("details edit <name:rest>", description="Изменить платёжные данные")
    async def details_edit(self, ctx: FeatureContext, name: str):
        text = ctx.message.text if ctx.message else ""
        inline = split_inline_details_edit(
            text, lambda n: self.details_infos.find_by(name=n)
        )
        if inline is not None:
            info, description = inline
            info.description = description
            await self.details_infos.save()
            await ctx.reply(f"Платежные данные для '{info.name}' обновлены")
            return
        clean_name = name.strip()
        info = self.details_infos.find_by(name=clean_name)
        if info is None:
            await ctx.reply(f"Платежные данные для '{clean_name}' не найдены")
            return
        await self.start_wizard(
            "bill:details_edit",
            ctx,
            details_name=info.name,
            current_description=info.description,
        )

    @subcommand(
        "<identifier:rest>",
        description="Отчёт по счёту (id/имя; добавь debug или edit)",
        catchall=True,
    )
    async def report_or_edit(self, ctx: FeatureContext, identifier: str):
        if not google_drive_available():
            await ctx.reply("Google Drive недоступен")
            return
        parts = identifier.split()
        if not parts:
            return False
        last = parts[-1].lower()
        debug_mode = last == "debug"
        edit_mode = last == "edit"
        ident_parts = parts[:-1] if (debug_mode or edit_mode) else parts
        ident = " ".join(ident_parts).strip()
        if not ident:
            if edit_mode:
                await ctx.reply("Использование: /bill {id} edit")
                return
            return False
        bill = self._find_bill(ident)
        if bill is None:
            await ctx.reply(f"Счет '{ident}' не найден")
            return
        if edit_mode:
            await self.start_wizard("bill:ocr", ctx, file_id=bill.file_id)
            return
        await self._send_bill_report(ctx, bill, debug_mode=debug_mode)

    @on_callback("bill:nav", schema="<target:str>")
    async def on_nav(self, ctx: FeatureContext, target: str):
        if target.startswith("~"):
            await ctx.toast()
            return
        bills = self.bills.all()
        if not bills:
            await ctx.toast("Нет счетов")
            return
        if not google_drive_available():
            await ctx.toast("Google Drive недоступен")
            return
        report = report_for_target(
            target, bills, list(self.payments), list(self.details_infos)
        )
        if report is None:
            await ctx.toast(f"Счет {target} не найден")
            return
        keyboard = build_bill_nav_keyboard(self.cb("bill:nav"), bills, target)
        chunks = split_long_message(report)
        text = chunks[0] if chunks else "Нет данных"
        parse_mode = "Markdown" if is_valid_markdown(text) else None
        await ctx.callback_query.message.edit_text(
            text=text, parse_mode=parse_mode, reply_markup=keyboard
        )
        await ctx.toast()

    @on_callback("bill:ocr_start", schema="<file_id:str>")
    async def on_ocr_start(self, ctx: FeatureContext, file_id: str):
        if not file_id:
            return
        await self.start_wizard("bill:ocr", ctx, file_id=file_id)

    @on_callback("bill:ocr_no", schema="")
    async def on_ocr_no(self, ctx: FeatureContext):
        try:
            await ctx.callback_query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await ctx.toast()

    @paginated("bills", per_page=15, header="📋 Счета")
    def bills_page(self, ctx: FeatureContext, metadata: str):
        items = sorted(self.bills.all(), key=lambda b: b.id)
        return items, format_bill_page

    @wizard(
        "bill:add",
        ask(
            "name",
            "Введите имя счета (имя файла на Google Диске):",
            validator=validate_message_text([
                check(lambda t: len(t.strip()) > 0, "Имя не может быть пустым")
            ]),
        ),
    )
    async def on_add_done(self, ctx: FeatureContext, name: str):
        await self._add_bill(ctx, name.strip())

    @wizard(
        "bill:details_add",
        ask(
            "description",
            "Введите описание платежных данных для пользователя:",
            validator=validate_message_text([
                check(lambda t: len(t.strip()) > 0, "Описание не может быть пустым")
            ]),
        ),
    )
    async def on_details_add_done(self, ctx: FeatureContext, name: str, description: str):
        await self._save_details(ctx, name, description.strip())

    @wizard(
        "bill:details_edit",
        ask(
            "description",
            lambda c: (
                f"Текущее описание для '{c['details_name']}':\n"
                f"{c['current_description']}\n\nВведите новое описание:"
            ),
            validator=validate_message_text([
                check(lambda t: len(t.strip()) > 0, "Описание не может быть пустым")
            ]),
        ),
    )
    async def on_details_edit_done(
        self,
        ctx: FeatureContext,
        details_name: str,
        current_description: str,
        description: str,
    ):
        info = self.details_infos.find_by(name=details_name)
        if info is None:
            return
        info.description = description.strip()
        await self.details_infos.save()
        await get_message(ctx.update).chat.send_message(
            f"Платежные данные для '{info.name}' обновлены"
        )

    @wizard(
        "bill:ocr",
        step(
            "collect",
            CollectBillContextStep(
                lambda **kw: f"bill:ocr_stop|{kw['file_id']}"
            ),
        ),
    )
    async def on_ocr_done(self, ctx: FeatureContext, file_id: str, **state):
        await finalize_ocr(self.repository, ctx.update, {"file_id": file_id, **state})

    async def _add_bill(self, ctx: FeatureContext, name: str):
        if not google_drive_available():
            await get_message(ctx.update).chat.send_message("Google Drive недоступен")
            return
        folder_id = get_bills_folder_id()
        file_id = find_file_in_folder(folder_id, name)
        if not file_id:
            templates = find_files_in_folder_by_name(folder_id, BILL_TEMPLATE_FILE_NAME)
            if not templates:
                await get_message(ctx.update).chat.send_message(
                    f"Файл '{name}' не найден, и шаблон '{BILL_TEMPLATE_FILE_NAME}' "
                    f"отсутствует в папке «финансы»."
                )
                return
            template_file_id = templates[0]
            renamed_file_id, error = rename_file(template_file_id, name)
            if not renamed_file_id:
                await get_message(ctx.update).chat.send_message(
                    f"Не удалось переименовать шаблон в '{name}': "
                    f"{error or 'неизвестная ошибка'}"
                )
                return
            file_id = renamed_file_id
        existing = self.bills.find_one(lambda b: b.name.lower() == name.lower())
        if existing:
            existing.file_id = file_id
            bill_id = existing.id
        else:
            new_bill = self.bills.add(Bill(id=0, name=name, file_id=file_id))
            bill_id = new_bill.id
        await self.bills.save()
        link = get_file_link(file_id)
        raw_rows = read_bill_raw_rows(file_id)
        transactions = parse_transactions_from_sheet(raw_rows)
        debts = debts_from_transactions(transactions)
        debts = net_direct_debts(debts)
        debts_list = debts_to_list(debts)
        closable = [bill_id] if not debts_list else None
        report = format_report(
            debts_list,
            [],
            list(self.details_infos),
            file_link=link,
            closable_bill_ids=closable,
        )
        lines = [f"✅ Счет '{name}' добавлен.", "", report]
        msg = "\n".join(lines)
        ocr_keyboard = build_bill_context_start_keyboard(
            self.cb("bill:ocr_start"), self.cb("bill:ocr_no"), file_id
        )
        chunks = split_long_message(msg)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            parse_mode = "Markdown" if is_valid_markdown(chunk) else None
            markup = ocr_keyboard if is_last else None
            await get_message(ctx.update).chat.send_message(
                chunk, parse_mode=parse_mode, reply_markup=markup
            )

    def _find_bill(self, identifier: str):
        try:
            bill_id = int(identifier)
            return self.bills.find_by(id=bill_id)
        except ValueError:
            target = identifier.lower()
            return self.bills.find_one(lambda b: b.name.lower() == target)

    async def _save_details(self, ctx: FeatureContext, name: str, description: str):
        existing = self.details_infos.find_by(name=name)
        if existing:
            existing.description = description
        else:
            self.details_infos.add(DetailsInfo(name=name, description=description))
        await self.details_infos.save()
        msg = get_message(ctx.update)
        await msg.chat.send_message(f"Платежные данные для '{name}' сохранены")

    async def _send_main_report(self, ctx: FeatureContext):
        bills = self.bills.all()
        if not bills:
            await ctx.reply("Нет счетов")
            return
        if not google_drive_available():
            await ctx.reply("Google Drive недоступен")
            return
        report = generate_main_report_text(
            bills, list(self.payments), list(self.details_infos)
        )
        keyboard = build_bill_nav_keyboard(self.cb("bill:nav"), bills, "общий")
        await self._send_chunks(ctx, report, keyboard)

    async def _send_bill_report(
        self, ctx: FeatureContext, bill: Bill, *, debug_mode: bool
    ):
        if debug_mode:
            raw_rows = read_bill_raw_rows(bill.file_id)
            debug_msg = format_debug_rows(raw_rows, bill.name)
            for chunk in split_long_message(debug_msg):
                await get_message(ctx.update).chat.send_message(chunk)
        report = generate_single_bill_report_text(
            bill, self.bills.all(), list(self.payments), list(self.details_infos)
        )
        ocr_keyboard = build_bill_context_start_keyboard(
            self.cb("bill:ocr_start"), self.cb("bill:ocr_no"), bill.file_id
        )
        await self._send_chunks(ctx, report, ocr_keyboard)

    async def _send_chunks(self, ctx: FeatureContext, text: str, last_keyboard):
        msg = get_message(ctx.update)
        chunks = split_long_message(text)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            markup = last_keyboard if is_last else None
            parse_mode = "Markdown" if is_valid_markdown(chunk) else None
            if i == 0 and ctx.message is not None:
                await ctx.message.reply_text(
                    chunk, parse_mode=parse_mode, reply_markup=markup
                )
            else:
                await msg.chat.send_message(
                    chunk, parse_mode=parse_mode, reply_markup=markup
                )
