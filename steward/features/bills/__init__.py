"""Telegram /bills feature — shared expense tracking.

Flow: /bills add <name> → collect photos/voice/text → AI parse → resolve names → confirm → save.
Non-authors can suggest additions; payments confirmed by creditor.

Architecture note: in-session callback handlers live on `_BillCollectStep` because the
session_handler intercepts callbacks before they reach `Feature.callback()`. Out-of-session
callbacks (list/view/close/payment confirmation/etc.) live on `BillsFeature` as `@on_callback`.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from steward.data.models.bill_v2 import (
    BillItemSuggestion,
    BillPaymentV2,
    BillV2,
    PaymentStatus,
    SuggestionStatus,
    UNKNOWN_PERSON_ID,
)
from steward.framework import (
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    on_callback,
    step,
    subcommand,
    wizard,
)
from steward.helpers.bills_money import minor_from_float, minor_to_display
from steward.helpers.bills_notifications import send_bill_notification
from steward.helpers.bills_person_match import match_name, update_chat_last_seen

from . import fmt, parse
from .session import _BillCollectStep, _PayingStep, _SessionState

logger = logging.getLogger(__name__)


class BillsFeature(Feature):
    command = "bills"
    description = "Управление совместными расходами"
    custom_prompt = (
        "/bills: создание и управление совместными расходами, "
        "добавление позиций в счёт, распознавание чеков по фото, "
        "регистрация платежей, просмотр долгов"
    )

    bill_persons = collection("bill_persons")
    bills_v2 = collection("bills_v2")
    bill_payments_v2 = collection("bill_payments_v2")
    bill_item_suggestions = collection("bill_item_suggestions")
    bill_notification_prefs = collection("bill_notification_prefs")
    users = collection("users")

    # -- Internal helpers --

    def _persons(self) -> dict[str, Any]:
        return {p.id: p for p in self.repository.db.bill_persons}

    def _users(self) -> dict[int, Any]:
        return {u.id: u for u in self.repository.db.users}

    def _chat_persons(self, author_tid: int) -> list:
        author = next((u for u in self.repository.db.users if u.id == author_tid), None)
        if not author:
            return [p for p in self.repository.db.bill_persons if p.telegram_id]
        author_chats = set(author.chat_ids)
        users_map = self._users()
        return [
            p for p in self.repository.db.bill_persons
            if p.telegram_id and (u := users_map.get(p.telegram_id)) and set(u.chat_ids) & author_chats
        ]

    def _person_bills(self, tid: int, all_mode: bool = False):
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        if all_mode and is_admin:
            user = next((u for u in self.repository.db.users if u.id == tid), None)
            cids = set(user.chat_ids) if user else set()
            bills = [
                b for b in self.repository.db.bills_v2
                if (person and (person.id == b.author_person_id or person.id in b.participants))
                or b.origin_chat_id in cids
            ]
        elif person:
            bills = self.repository.get_bills_v2_for_person(person.id)
        else:
            bills = []
        return person, is_admin, bills

    # -- Subcommands --

    @subcommand("", description="Список открытых счетов и долгов")
    async def cmd_list(self, ctx: FeatureContext):
        await self._show_overview(ctx, all_mode=False)

    @subcommand("all", description="Все счета (только админ)")
    async def cmd_list_all(self, ctx: FeatureContext):
        await self._show_overview(ctx, all_mode=True)

    @subcommand("help", description="Справка")
    async def cmd_help(self, ctx: FeatureContext):
        await ctx.reply(
            "📖 *Справка /bills*\n\n"
            "/bills — список счетов и долги\n"
            "/bills add <название> — создать счёт\n"
            "/bills <id> — посмотреть счёт\n"
            "/bills pay <сумма> @user — зарегистрировать платёж\n"
            "/bills alias <имя> = <псевдоним> — добавить псевдоним\n"
            "/bills notify — настройки уведомлений\n"
            "/bills all — все счета (админ)"
        )

    @subcommand("<bill_id:int>", description="Посмотреть счёт")
    async def cmd_view(self, ctx: FeatureContext, bill_id: int):
        await self._show_bill(ctx, bill_id)

    @subcommand("add", description="Создать счёт (запросит название)")
    async def cmd_add_no_name(self, ctx: FeatureContext):
        await self._start_create(ctx, name="")

    @subcommand("add <name:rest>", description="Создать счёт с названием")
    async def cmd_add(self, ctx: FeatureContext, name: str):
        await self._start_create(ctx, name=name.strip())

    @subcommand("pay <amount:float> <target:rest>", description="Зарегистрировать платёж")
    async def cmd_pay(self, ctx: FeatureContext, amount: float, target: str):
        target = target.strip()
        if not target:
            await ctx.reply("Формат: /bills pay 100 @username\nили: /bills pay 50.50 Имя")
            return
        try:
            amount_minor = minor_from_float(amount)
        except ValueError:
            await ctx.reply("Неверная сумма.")
            return
        await self._create_payment_for_user(
            ctx.bot,
            from_user=ctx.message.from_user,
            amount_minor=amount_minor,
            target_name=target.lstrip("@"),
            chat_id=ctx.chat_id,
            bill_id=None,
            reply_chat_id=ctx.chat_id,
        )

    @subcommand("alias <text:rest>", description="Псевдоним: имя = псевдоним")
    async def cmd_alias(self, ctx: FeatureContext, text: str):
        text = text.strip()
        if not text:
            await ctx.reply("Формат: /bills alias Лёша = Алексей")
            return
        m = re.match(r"(.+?)\s*=\s*(.+)", text)
        if not m:
            await ctx.reply("Формат: /bills alias Имя = Псевдоним")
            return
        target_name, alias = m.group(1).strip(), m.group(2).strip()
        person, candidates = match_name(
            target_name,
            self.repository.db.bill_persons,
            self._users(),
            caller_telegram_id=ctx.user_id,
            origin_chat_id=ctx.chat_id,
        )
        if not person:
            msg = (
                f"Несколько совпадений для «{target_name}»."
                if candidates
                else f"«{target_name}» не найден."
            )
            await ctx.reply(msg)
            return
        new_aliases = [a.strip() for a in re.split(r"[,\s]+", alias) if a.strip()]
        added = [a for a in new_aliases if a not in person.aliases]
        person.aliases.extend(added)
        if added:
            await self.repository.save()
        await ctx.reply(
            f"✅ Добавлено {len(added)} псевдонимов для {person.display_name}: {', '.join(added)}"
        )

    @subcommand("notify", description="Настройки уведомлений")
    async def cmd_notify_show(self, ctx: FeatureContext):
        prefs = self.repository.get_bill_notification_prefs(ctx.user_id)
        await ctx.reply(
            f"⚙️ Тихий режим: {prefs.quiet_start}:00–{prefs.quiet_end}:00\n\n"
            f"Изменить: /bills notify quiet 22 8\nОтключить: /bills notify quiet 0 24"
        )

    @subcommand(
        "notify quiet <start_hour:int> <end_hour:int>",
        description="Тихие часы: /bills notify quiet 22 8",
    )
    async def cmd_notify_quiet(self, ctx: FeatureContext, start_hour: int, end_hour: int):
        if not (0 <= start_hour <= 23 and 0 <= end_hour <= 24):
            await ctx.reply("Часы: 0–23 (начало), 0–24 (конец).")
            return
        prefs = self.repository.get_bill_notification_prefs(ctx.user_id)
        prefs.quiet_start, prefs.quiet_end = start_hour, end_hour
        await self.repository.save()
        await ctx.reply(f"✅ Тихий режим: {start_hour}:00–{end_hour}:00")

    # -- Common dispatch helpers --

    async def _show_overview(self, ctx: FeatureContext, all_mode: bool):
        tid = ctx.user_id
        person, is_admin, bills = self._person_bills(tid, all_mode)
        logger.info(
            "/bills list: tid=%s person=%s is_admin=%s bills=%d",
            tid, person.id if person else None, is_admin, len(bills),
        )
        if not bills:
            await ctx.reply("У тебя пока нет счетов. Создай первый: /bills add <название>")
            return

        by_id = self._persons()
        text = fmt.format_overview(bills, person.id if person else None, by_id, self.repository.db.bill_payments_v2)
        if all_mode:
            text += "\n_(режим: все чаты)_"

        open_bills = [b for b in bills if not b.closed]
        bill_buttons = fmt.kb_bill_buttons(self, open_bills)
        rows = fmt.compact_grid(bill_buttons, max_cols=2, max_rows=10)
        rows.append([self.cb("bills:new").button("➕ Новый счёт")])
        await ctx.reply(text, keyboard=Keyboard.grid(rows))

    async def _show_bill(self, ctx: FeatureContext, bill_id: int):
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.reply(f"Счёт \\#{bill_id} не найден.")
            return
        tid = ctx.user_id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        pid = person.id if person else None
        if not is_admin and pid not in (bill.participants + [bill.author_person_id]):
            await ctx.reply("Нет доступа к этому счёту.")
            return
        by_id = self._persons()
        payments = self.repository.db.bill_payments_v2
        await ctx.reply(
            fmt.format_bill_detail(bill, pid, by_id, payments),
            keyboard=fmt.kb_bill(self, bill, pid, is_admin, payments),
        )

    async def _start_create(self, ctx: FeatureContext, name: str):
        chat_id = ctx.chat_id
        tid = ctx.user_id
        if not name:
            state = _SessionState(
                phase="naming",
                bill_name="",
                origin_chat_id=chat_id,
                caller_tid=tid,
            )
        else:
            state = _SessionState(
                phase="collect",
                bill_name=name,
                origin_chat_id=chat_id,
                caller_tid=tid,
            )
        await self.start_wizard("bills:session", ctx, state=state, _feature=self)

    # -- Out-of-session callbacks --

    @on_callback("bills:list_open", schema="")
    async def on_list_open(self, ctx: FeatureContext):
        await self._on_list(ctx, closed=False)

    @on_callback("bills:list_closed", schema="")
    async def on_list_closed(self, ctx: FeatureContext):
        await self._on_list(ctx, closed=True)

    async def _on_list(self, ctx: FeatureContext, closed: bool):
        tid = ctx.user_id
        person, is_admin, bills = self._person_bills(tid)
        logger.info(
            "_on_list: tid=%s person=%s bills=%d closed=%s",
            tid, person.id if person else None, len(bills), closed,
        )
        filtered = [b for b in bills if b.closed == closed]
        if not filtered:
            await ctx.edit("Нет закрытых счетов." if closed else "Нет открытых счетов.")
            return
        bill_buttons = fmt.kb_bill_buttons(self, filtered)
        rows = fmt.compact_grid(bill_buttons, max_cols=2, max_rows=10)
        if not closed:
            rows.append([self.cb("bills:new").button("➕ Новый")])
        label = "📕 *Закрытые счета:*" if closed else "📋 *Открытые счета:*"
        await ctx.edit(label, keyboard=Keyboard.grid(rows))

    @on_callback("bills:new", schema="")
    async def on_new(self, ctx: FeatureContext):
        chat_id = ctx.chat_id
        tid = ctx.user_id
        try:
            await ctx.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        state = _SessionState(phase="naming", bill_name="", origin_chat_id=chat_id, caller_tid=tid)
        await self.start_wizard("bills:session", ctx, state=state, _feature=self)

    @on_callback("bills:view", schema="<bill_id:int>")
    async def on_view(self, ctx: FeatureContext, bill_id: int):
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.edit(f"Счёт \\#{bill_id} не найден.")
            return
        tid = ctx.user_id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        pid = person.id if person else None
        if not is_admin and pid not in (bill.participants + [bill.author_person_id]):
            await ctx.toast("Нет доступа.", alert=True)
            return
        by_id = self._persons()
        payments = self.repository.db.bill_payments_v2
        await ctx.edit(
            fmt.format_bill_detail(bill, pid, by_id, payments),
            keyboard=fmt.kb_bill(self, bill, pid, is_admin, payments),
        )

    @on_callback("bills:close", schema="<bill_id:int>")
    async def on_close(self, ctx: FeatureContext, bill_id: int):
        await self._set_closed(ctx, bill_id, close=True)

    @on_callback("bills:reopen", schema="<bill_id:int>")
    async def on_reopen(self, ctx: FeatureContext, bill_id: int):
        await self._set_closed(ctx, bill_id, close=False)

    async def _set_closed(self, ctx: FeatureContext, bill_id: int, close: bool):
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.toast("Счёт не найден.", alert=True)
            return
        tid = ctx.user_id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        if not is_admin and (not person or person.id != bill.author_person_id):
            await ctx.toast("Нет прав.", alert=True)
            return

        bill.closed = close
        bill.closed_at = datetime.now() if close else None
        await self.repository.save()

        if close:
            from steward.helpers.bills_money import compute_bill_debts, net_debts, apply_payments
            raw = compute_bill_debts(bill.transactions, bill.currency)
            net = net_debts(raw)
            bp = [p for p in self.repository.db.bill_payments_v2 if bill.id in p.bill_ids]
            after = apply_payments(net, bp, clamp_zero=True)
            has_debts = any(a > 0 for creds in after.values() for a in creds.values())
            msg = f"🔒 Счёт «{bill.name}» закрыт."
            if has_debts:
                msg += "\n⚠️ Остались неоплаченные долги!"
            await ctx.edit(msg)
        else:
            pid = person.id if person else None
            by_id = self._persons()
            payments = self.repository.db.bill_payments_v2
            await ctx.edit(
                fmt.format_bill_detail(bill, pid, by_id, payments),
                keyboard=fmt.kb_bill(self, bill, pid, is_admin, payments),
            )

    @on_callback("bills:pay_start", schema="<bill_id:int>")
    async def on_pay_start(self, ctx: FeatureContext, bill_id: int):
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.toast("Счёт не найден.", alert=True)
            return
        tid = ctx.user_id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        pid = person.id if person else None
        if not pid:
            await ctx.toast("Ты не участник этого счёта.", alert=True)
            return

        by_id = self._persons()
        payments = self.repository.db.bill_payments_v2
        text, kb = fmt.kb_pay_global(self, pid, by_id, self.repository.db.bills_v2, payments, bill.id)
        await ctx.edit(text, keyboard=kb, markdown=False)

    @on_callback("bills:pay_manual", schema="<bill_id:int>")
    async def on_pay_manual(self, ctx: FeatureContext, bill_id: int):
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.toast("Счёт не найден.", alert=True)
            return
        tid = ctx.user_id
        chat_id = ctx.chat_id
        await self.start_session(
            [_PayingStep()],
            ctx,
            paying={
                "target_bill_id": bill.id,
                "origin_chat_id": chat_id,
                "caller_tid": tid,
                "bill_name": bill.name,
            },
            _feature=self,
        )

    @on_callback(
        "bills:qpay",
        schema="<bill_id:int>|<creditor_short:str>|<amount:int>",
    )
    async def on_quick_pay(
        self, ctx: FeatureContext, bill_id: int, creditor_short: str, amount: int
    ):
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.toast("Счёт не найден.", alert=True)
            return
        tid = ctx.user_id
        user = ctx.callback_query.from_user
        debtor, _ = self.repository.get_or_create_bill_person(
            telegram_id=tid,
            display_name=user.full_name or str(tid),
            username=user.username,
        )
        creditor = next(
            (p for p in self.repository.db.bill_persons if p.id.startswith(creditor_short)),
            None,
        )
        if not creditor:
            await ctx.toast("Получатель не найден.", alert=True)
            return

        chat_id = ctx.chat_id
        await self._register_payment(ctx.bot, debtor, creditor, amount, bill.currency, chat_id)
        await ctx.edit(
            f"💸 Платёж {minor_to_display(amount, bill.currency)} → {creditor.display_name} зарегистрирован.\n"
            f"Ждём подтверждения."
        )

    # In-session callback schemas (registered so feature.cb() can build buttons; bodies
    # are no-ops because the active session intercepts these callbacks before they reach here).

    @on_callback("bills:add_done", schema="")
    async def on_add_done(self, ctx: FeatureContext):
        pass

    @on_callback("bills:add_cancel", schema="")
    async def on_add_cancel(self, ctx: FeatureContext):
        pass

    @on_callback("bills:add_confirm", schema="")
    async def on_add_confirm(self, ctx: FeatureContext):
        pass

    @on_callback("bills:add_more", schema="")
    async def on_add_more(self, ctx: FeatureContext):
        pass

    @on_callback("bills:name_pick", schema="<person_id:str>")
    async def on_name_pick(self, ctx: FeatureContext, person_id: str):
        pass

    @on_callback("bills:name_new", schema="")
    async def on_name_new(self, ctx: FeatureContext):
        pass

    @on_callback("bills:q_pick", schema="<idx:int>")
    async def on_q_pick(self, ctx: FeatureContext, idx: int):
        pass

    @on_callback("bills:change_list", schema="")
    async def on_change_list(self, ctx: FeatureContext):
        pass

    @on_callback("bills:change_back", schema="")
    async def on_change_back(self, ctx: FeatureContext):
        pass

    @on_callback("bills:chg", schema="<idx:int>")
    async def on_chg(self, ctx: FeatureContext, idx: int):
        pass

    @on_callback("bills:chgp", schema="<idx:int>|<person_id:str>")
    async def on_chgp(self, ctx: FeatureContext, idx: int, person_id: str):
        pass

    @on_callback("bills:chgn", schema="<idx:int>")
    async def on_chgn(self, ctx: FeatureContext, idx: int):
        pass

    @on_callback("bills:noop", schema="")
    async def on_noop(self, ctx: FeatureContext):
        pass

    @on_callback("bills:suggest_start", schema="<bill_id:int>")
    async def on_suggest_start(self, ctx: FeatureContext, bill_id: int):
        bill = self.repository.get_bill_v2(bill_id)
        if not bill or bill.closed:
            await ctx.edit("Счёт закрыт или не найден.")
            return
        tid = ctx.user_id
        chat_id = ctx.chat_id
        state = _SessionState(
            phase="collect",
            bill_name=bill.name,
            origin_chat_id=chat_id,
            caller_tid=tid,
            is_suggestion=True,
            target_bill_id=bill_id,
        )
        try:
            await ctx.edit(
                f"Предложение для «{bill.name}».\nОтправляй фото, голосовые или текст.",
                keyboard=fmt.kb_collect(self, state.context_items),
            )
        except Exception:
            pass
        if ctx.callback_query and ctx.callback_query.message:
            state.last_kb_chat = ctx.callback_query.message.chat_id
            state.last_kb_msg = ctx.callback_query.message.message_id
        state.announced = True
        await self.start_wizard("bills:session", ctx, state=state, _feature=self)

    @on_callback("bills:suggest_approve", schema="<suggestion_id:str>")
    async def on_suggest_approve(self, ctx: FeatureContext, suggestion_id: str):
        await self._on_suggest_decide(ctx, suggestion_id, approve=True)

    @on_callback("bills:suggest_reject", schema="<suggestion_id:str>")
    async def on_suggest_reject(self, ctx: FeatureContext, suggestion_id: str):
        await self._on_suggest_decide(ctx, suggestion_id, approve=False)

    @on_callback("bills:suggest_skip", schema="")
    async def on_suggest_skip(self, ctx: FeatureContext):
        pass

    async def _on_suggest_decide(self, ctx: FeatureContext, suggestion_id: str, approve: bool):
        suggestion = self.repository.get_bill_suggestion(suggestion_id)
        if not suggestion or suggestion.status != SuggestionStatus.PENDING:
            await ctx.toast("Предложение уже обработано.", alert=True)
            return
        bill = self.repository.get_bill_v2(suggestion.bill_id)
        if not bill:
            await ctx.toast("Счёт не найден.", alert=True)
            return
        tid = ctx.user_id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        if not is_admin and (not person or person.id != bill.author_person_id):
            await ctx.toast("Нет прав.", alert=True)
            return

        if approve:
            if (
                suggestion.bill_updated_at_propose
                and bill.updated_at != suggestion.bill_updated_at_propose
            ):
                await ctx.toast("Счёт изменился. Проверь вручную.", alert=True)
                return
            for tx in suggestion.proposed_tx:
                tx.id = str(uuid.uuid4())
                tx.added_by_person_id = suggestion.proposed_by_person_id
                bill.transactions.append(tx)
            if suggestion.proposed_by_person_id not in bill.participants:
                bill.participants.append(suggestion.proposed_by_person_id)
            bill.updated_at = datetime.now()
            suggestion.status = SuggestionStatus.APPROVED
        else:
            suggestion.status = SuggestionStatus.REJECTED

        suggestion.decided_by_person_id = person.id if person else None
        suggestion.decided_at = datetime.now()

        proposer = self.repository.get_bill_person(suggestion.proposed_by_person_id)
        if proposer:
            emoji = "✅" if approve else "❌"
            verb = "одобрено" if approve else "отклонено"
            await send_bill_notification(
                ctx.bot,
                self.repository,
                proposer,
                f"{emoji} Твоё предложение в «{bill.name}» {verb}.",
                initiated_chat_id=suggestion.origin_chat_id,
            )

        await self.repository.save()
        if approve:
            await ctx.edit(
                f"✅ Одобрено, {len(suggestion.proposed_tx)} позиций добавлено в «{bill.name}»."
            )
        else:
            await ctx.edit("❌ Предложение отклонено.")

    @on_callback("bills:pay_confirm", schema="<payment_id:str>")
    async def on_pay_confirm(self, ctx: FeatureContext, payment_id: str):
        await self._on_pay_decide(ctx, payment_id, confirm=True)

    @on_callback("bills:pay_reject", schema="<payment_id:str>")
    async def on_pay_reject(self, ctx: FeatureContext, payment_id: str):
        await self._on_pay_decide(ctx, payment_id, confirm=False)

    async def _on_pay_decide(self, ctx: FeatureContext, payment_id: str, confirm: bool):
        payment = self.repository.get_bill_payment_v2(payment_id)
        if not payment or payment.status != PaymentStatus.PENDING:
            await ctx.toast("Платёж уже обработан.", alert=True)
            return
        tid = ctx.user_id
        creditor = self.repository.get_bill_person(payment.creditor)
        is_admin = self.repository.is_admin(tid)
        if not is_admin and (not creditor or creditor.telegram_id != tid):
            await ctx.toast("Только получатель может ответить.", alert=True)
            return

        payment.status = PaymentStatus.CONFIRMED if confirm else PaymentStatus.REJECTED

        if confirm:
            debtor = self.repository.get_bill_person(payment.debtor)
            name = debtor.display_name if debtor else "?"
            msg = (
                f"✅ Получение {minor_to_display(payment.amount_minor, payment.currency)} "
                f"от {name} подтверждено."
            )

            from steward.helpers.bills_money import compute_bill_debts, net_debts, apply_payments
            for bill_id in payment.bill_ids:
                bill = self.repository.get_bill_v2(bill_id)
                if not bill or bill.closed:
                    continue
                raw = compute_bill_debts(bill.transactions, bill.currency)
                net = net_debts(raw)
                bp = [p for p in self.repository.db.bill_payments_v2 if bill_id in p.bill_ids]
                after = apply_payments(net, bp, clamp_zero=True)
                has_debts = any(a > 0 for creds in after.values() for a in creds.values())
                if not has_debts:
                    bill.closed = True
                    bill.closed_at = datetime.now()
                    msg += f"\n🔒 Счёт «{bill.name}» автоматически закрыт — все долги оплачены!"

            await ctx.edit(msg)
        else:
            await ctx.edit("❌ Получение не подтверждено.")

        await self.repository.save()

    # -- Wizard --

    @wizard("bills:session", step("flow", _BillCollectStep()))
    async def on_wizard_done(self, ctx: FeatureContext, **state):
        pass

    # -- Save (called from Step) --

    async def _save_bill(self, bot, st: _SessionState, user, send_callback):
        caller, _ = self.repository.get_or_create_bill_person(
            telegram_id=st.caller_tid,
            display_name=user.full_name or str(st.caller_tid),
            username=user.username,
        )

        participant_ids = [caller.id]
        for tx in st.parsed_transactions:
            for asg in tx.assignments:
                for d in asg.debtors:
                    if d and d not in participant_ids:
                        participant_ids.append(d)
            if tx.creditor and tx.creditor not in participant_ids:
                participant_ids.append(tx.creditor)
        participants = [p for p in participant_ids if p != UNKNOWN_PERSON_ID]

        bill = BillV2(
            id=self.repository.get_next_bill_v2_id(),
            name=st.bill_name,
            author_person_id=caller.id,
            participants=participants,
            transactions=st.parsed_transactions,
            currency=st.currency,
            origin_chat_id=st.origin_chat_id,
            updated_at=datetime.now(),
        )
        self.repository.db.bills_v2.append(bill)

        by_id = self._persons()
        for pid in participants:
            if p := by_id.get(pid):
                update_chat_last_seen(p, st.origin_chat_id)

        if any(tx.incomplete for tx in st.parsed_transactions):
            from steward.delayed_action.bill_incomplete_nudge import schedule_incomplete_nudge
            schedule_incomplete_nudge(self.repository, bill.id)

        await self.repository.save()

        by_id = self._persons()
        text = fmt.format_bill_created(bill, by_id)
        kb = fmt.kb_bill(
            self,
            bill,
            caller.id,
            self.repository.is_admin(st.caller_tid),
            self.repository.db.bill_payments_v2,
        )
        await send_callback(text, keyboard=kb)

    async def _save_suggestion(self, bot, st: _SessionState, user, send_callback):
        bill = self.repository.get_bill_v2(st.target_bill_id)
        if not bill or bill.closed:
            await send_callback("Счёт больше недоступен.")
            return

        proposer = self.repository.get_bill_person_by_telegram_id(st.caller_tid)
        if not proposer:
            proposer, _ = self.repository.get_or_create_bill_person(
                telegram_id=st.caller_tid,
                display_name=user.full_name or str(st.caller_tid),
                username=user.username,
            )

        suggestion = BillItemSuggestion(
            id=str(uuid.uuid4()),
            bill_id=bill.id,
            proposed_by_person_id=proposer.id,
            proposed_tx=st.parsed_transactions,
            origin_chat_id=st.origin_chat_id,
            bill_updated_at_propose=bill.updated_at,
        )
        self.repository.db.bill_item_suggestions.append(suggestion)

        author = self.repository.get_bill_person(bill.author_person_id)
        if author:
            lines = [
                f"🧾 {proposer.display_name} предлагает добавить в «{bill.name}» \\#{bill.id}:"
            ]
            for tx in suggestion.proposed_tx[:5]:
                total = minor_to_display(tx.unit_price_minor * tx.quantity, bill.currency)
                lines.append(f"  • {tx.item_name} × {tx.quantity} — {total}")
            if len(suggestion.proposed_tx) > 5:
                lines.append(f"  … и ещё {len(suggestion.proposed_tx) - 5}")

            kb = Keyboard.row(
                self.cb("bills:suggest_approve").button("✅ Одобрить", suggestion_id=suggestion.id),
                self.cb("bills:suggest_reject").button("❌ Отклонить", suggestion_id=suggestion.id),
            )
            msg = await send_bill_notification(
                bot,
                self.repository,
                author,
                "\n".join(lines),
                reply_markup=kb.to_markup(),
                initiated_chat_id=suggestion.origin_chat_id,
            )
            if msg:
                suggestion.approval_chat_id = msg.chat_id
                suggestion.approval_message_id = msg.message_id

        from steward.delayed_action.bill_suggestion_lifecycle import schedule_suggestion_lifecycle
        schedule_suggestion_lifecycle(self.repository, suggestion.id)

        await self.repository.save()
        await send_callback(f"📤 Предложение отправлено автору «{bill.name}».")

    # -- Payment helpers --

    def _find_bill_ids_for_pair(self, debtor_id: str, creditor_id: str) -> list[int]:
        from steward.helpers.bills_money import compute_bill_debts, net_debts, apply_payments
        result = []
        for bill in self.repository.db.bills_v2:
            if bill.closed:
                continue
            if debtor_id not in bill.participants and debtor_id != bill.author_person_id:
                continue
            raw = compute_bill_debts(bill.transactions, bill.currency)
            net = net_debts(raw)
            bp = [p for p in self.repository.db.bill_payments_v2 if bill.id in p.bill_ids]
            after = apply_payments(net, bp, clamp_zero=True)
            if after.get(debtor_id, {}).get(creditor_id, 0) > 0:
                result.append(bill.id)
        return result

    async def _register_payment(
        self,
        bot,
        debtor,
        creditor,
        amount_minor: int,
        currency: str,
        chat_id: int,
        bill_ids: list[int] | None = None,
    ):
        all_bill_ids = bill_ids if bill_ids else self._find_bill_ids_for_pair(debtor.id, creditor.id)
        payment = BillPaymentV2(
            id=str(uuid.uuid4()),
            debtor=debtor.id,
            creditor=creditor.id,
            amount_minor=amount_minor,
            currency=currency,
            status=PaymentStatus.PENDING,
            initiated_chat_id=chat_id,
            bill_ids=all_bill_ids,
        )
        self.repository.db.bill_payments_v2.append(payment)

        from steward.delayed_action.bill_payment_reminder import schedule_payment_reminder
        schedule_payment_reminder(self.repository, payment.id)

        kb = Keyboard.row(
            self.cb("bills:pay_confirm").button("✅ Получил", payment_id=payment.id),
            self.cb("bills:pay_reject").button("❌ Не получал", payment_id=payment.id),
        )
        amount_str = minor_to_display(amount_minor, currency)
        mention = (
            f"[{creditor.display_name}](tg://user?id={creditor.telegram_id})"
            if creditor.telegram_id
            else creditor.display_name
        )
        notif = await send_bill_notification(
            bot,
            self.repository,
            creditor,
            f"💸 {debtor.display_name} говорит, что перевёл {mention} *{amount_str}*\nПодтверди получение:",
            sender=debtor,
            reply_markup=kb.to_markup(),
            parse_mode="Markdown",
            initiated_chat_id=chat_id,
        )
        if notif:
            payment.confirmation_chat_id = notif.chat_id
            payment.confirmation_message_id = notif.message_id
        logger.info(
            "Payment %s created: %s -> %s %s, notified=%s",
            payment.id[:8], debtor.display_name, creditor.display_name, amount_str, bool(notif),
        )
        await self.repository.save()
        return payment

    async def _create_payment_for_user(
        self,
        bot,
        from_user,
        amount_minor: int,
        target_name: str,
        chat_id: int,
        *,
        bill_id: int | None,
        reply_chat_id: int,
    ):
        debtor, _ = self.repository.get_or_create_bill_person(
            telegram_id=from_user.id,
            display_name=from_user.full_name or str(from_user.id),
            username=from_user.username,
        )
        creditor, candidates = match_name(
            target_name.lstrip("@"),
            self.repository.db.bill_persons,
            self._users(),
            caller_telegram_id=from_user.id,
            origin_chat_id=chat_id,
        )
        if not creditor:
            text = (
                f"«{target_name}» неоднозначно: {', '.join(p.display_name for p in candidates[:5])}."
                if candidates
                else f"Не нашёл «{target_name}»."
            )
            await bot.send_message(chat_id=reply_chat_id, text=text)
            return

        currency = (self.repository.get_bill_v2(bill_id).currency if bill_id else None) or "BYN"

        await self._register_payment(bot, debtor, creditor, amount_minor, currency, chat_id)
        await bot.send_message(
            chat_id=reply_chat_id,
            text=(
                f"💸 Платёж {minor_to_display(amount_minor, currency)} → "
                f"{creditor.display_name} зарегистрирован. Ждём подтверждения."
            ),
        )
