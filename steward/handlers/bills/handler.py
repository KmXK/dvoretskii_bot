"""Telegram /bills handler — shared expense tracking.

Flow: /bills add <name> → collect photos/voice/text → AI parse → resolve names → confirm → save.
Non-authors can suggest additions; payments confirmed by creditor.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import CallbackBotContext, ChatBotContext
from steward.data.models.bill_v2 import (
    BillItemSuggestion,
    BillPaymentV2,
    BillV2,
    PaymentStatus,
    SuggestionStatus,
    UNKNOWN_PERSON_ID,
)
from steward.handlers.handler import Handler
from steward.helpers.ai import get_prompt, make_openrouter_query, OpenRouterModel
from steward.helpers.bills_money import minor_from_float, minor_to_display
from steward.helpers.bills_notifications import send_bill_notification
from steward.helpers.bills_person_match import match_name, update_chat_last_seen
from steward.helpers.command_validation import validate_command_msg

from . import fmt, media, parse

logger = logging.getLogger(__name__)


def _bill_ocr_prompt() -> str:
    return get_prompt("bill_ocr")


# ── Session ───────────────────────────────────────────────────────────────────

@dataclass
class _Session:
    phase: str                               # naming|collect|questions|answering|resolve|confirm|paying
    bill_name: str
    origin_chat_id: int
    caller_tid: int
    is_suggestion: bool = False
    target_bill_id: int | None = None
    currency: str = "BYN"
    context_items: list[str] = field(default_factory=list)
    parsed_transactions: list = field(default_factory=list)
    parsed_rows: list[dict] = field(default_factory=list)
    new_person_names: list[str] = field(default_factory=list)
    resolve_queue: list[tuple[str, list]] = field(default_factory=list)
    resolved_map: dict[str, str] = field(default_factory=dict)
    question_queue: list[dict] = field(default_factory=list)
    last_kb_chat: int | None = None
    last_kb_msg: int | None = None


# ── Handler ───────────────────────────────────────────────────────────────────

class BillsHandler(Handler):
    def __init__(self):
        self._s: dict[tuple[int, int], _Session] = {}

    # -- Shortcuts --

    def _key(self, ctx) -> tuple[int, int]:
        if hasattr(ctx, "callback_query") and ctx.callback_query:
            return ctx.callback_query.from_user.id, ctx.callback_query.message.chat_id
        return ctx.message.from_user.id, ctx.message.chat_id

    def _user(self, ctx):
        if hasattr(ctx, "callback_query") and ctx.callback_query:
            return ctx.callback_query.from_user
        return ctx.message.from_user

    def _persons(self):
        return {p.id: p for p in self.repository.db.bill_persons}

    def _users(self):
        return {u.id: u for u in self.repository.db.users}

    def _chat_persons(self, author_tid: int) -> list:
        """Bill persons who share at least one chat with the author."""
        author = next((u for u in self.repository.db.users if u.id == author_tid), None)
        if not author:
            return [p for p in self.repository.db.bill_persons if p.telegram_id]
        author_chats = set(author.chat_ids)
        users_map = self._users()
        return [p for p in self.repository.db.bill_persons
                if p.telegram_id and (u := users_map.get(p.telegram_id)) and set(u.chat_ids) & author_chats]

    def _person_bills(self, tid: int, all_mode=False):
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        if all_mode and is_admin:
            user = next((u for u in self.repository.db.users if u.id == tid), None)
            cids = set(user.chat_ids) if user else set()
            bills = [b for b in self.repository.db.bills_v2
                     if (person and (person.id == b.author_person_id or person.id in b.participants))
                     or b.origin_chat_id in cids]
        elif person:
            bills = self.repository.get_bills_v2_for_person(person.id)
        else:
            bills = []
        return person, is_admin, bills

    # -- Session helpers --

    async def _clear_kb(self, ctx, s: _Session):
        if not s.last_kb_msg:
            return
        try:
            await ctx.bot.edit_message_reply_markup(
                chat_id=s.last_kb_chat, message_id=s.last_kb_msg, reply_markup=None,
            )
        except Exception:
            pass
        s.last_kb_msg = s.last_kb_chat = None

    async def _reply(self, ctx, text: str, s: _Session | None = None, reply_markup=None, edit: bool | None = None, **kw):
        kw.setdefault("parse_mode", "Markdown")
        is_cb = hasattr(ctx, "callback_query") and ctx.callback_query
        should_edit = edit if edit is not None else is_cb

        # Try editing: prefer last_kb_msg (bot's own message), fallback to callback message
        if should_edit:
            edit_target = None
            if s and s.last_kb_msg and s.last_kb_chat:
                edit_target = (s.last_kb_chat, s.last_kb_msg)
            elif is_cb:
                edit_target = (ctx.callback_query.message.chat_id, ctx.callback_query.message.message_id)

            if edit_target:
                try:
                    msg = await ctx.bot.edit_message_text(
                        text, chat_id=edit_target[0], message_id=edit_target[1],
                        reply_markup=reply_markup, **kw,
                    )
                    if s:
                        s.last_kb_msg, s.last_kb_chat = (msg.message_id, msg.chat_id) if reply_markup else (None, None)
                    return msg
                except Exception as e:
                    logger.debug("_reply edit failed (chat=%s msg=%s): %s", edit_target[0], edit_target[1], e)

        if s:
            await self._clear_kb(ctx, s)
        target = ctx.callback_query.message if is_cb else ctx.message
        msg = await target.reply_text(text, reply_markup=reply_markup, **kw)
        if s:
            s.last_kb_msg, s.last_kb_chat = msg.message_id, msg.chat_id
        return msg

    # ── Entry points ───────────────────────────────────────────────────��──────

    async def chat(self, ctx: ChatBotContext) -> bool:
        msg = ctx.message
        if not msg:
            return False
        s = self._s.get(self._key(ctx))
        if s:
            return await self._on_input(ctx, s)
        if not msg.text:
            return False
        v = validate_command_msg(ctx.update, "bills", r"(?P<args>.*)?")
        if not v:
            return False
        logger.info("bills chat: user=%s text=%s", msg.from_user.id, msg.text[:50])
        return await self._dispatch(ctx, (v.args or {}).get("args", "").strip())

    async def _dispatch(self, ctx: ChatBotContext, args: str) -> bool:
        if not args:                              return await self._cmd_list(ctx)
        if args == "all":                         return await self._cmd_list(ctx, all_mode=True)
        if args == "help":                        return await self._cmd_help(ctx)
        if re.fullmatch(r"\d+", args):            return await self._cmd_view(ctx, int(args))
        if m := re.match(r"add\s*(.*)", args, re.I):  return await self._cmd_add(ctx, m.group(1).strip())
        if m := re.match(r"pay\s+(.*)", args, re.I):  return await self._cmd_pay(ctx, m.group(1).strip())
        if m := re.match(r"alias\s*(.*)", args, re.I): return await self._cmd_alias(ctx, m.group(1).strip())
        if m := re.match(r"notify\s*(.*)", args, re.I): return await self._cmd_notify(ctx, m.group(1).strip())
        await ctx.message.reply_text("Неизвестная команда. /bills help")
        return True

    async def callback(self, ctx: CallbackBotContext) -> bool:
        data = ctx.callback_query.data or ""
        if not data.startswith("bills_"):
            return False
        tid = ctx.callback_query.from_user.id
        logger.info("bills callback: %s from user %s", data, tid)
        await ctx.callback_query.answer()

        parts = data.split("|", 3)
        action, *args = parts

        match action:
            case "bills_list_open":                     return await self._on_list(ctx, closed=False)
            case "bills_list_closed":                   return await self._on_list(ctx, closed=True)
            case "bills_new":                           return await self._on_new(ctx)
            case "bills_view" if args:                  return await self._on_view(ctx, int(args[0]))
            case "bills_close" if args:                 return await self._on_close(ctx, int(args[0]), close=True)
            case "bills_reopen" if args:                return await self._on_close(ctx, int(args[0]), close=False)
            case "bills_pay_start" if args:             return await self._on_pay_start(ctx, int(args[0]))
            case "bills_pay_manual" if args:            return await self._on_pay_manual(ctx, int(args[0]))
            case "bills_qpay" if len(args) >= 3:        return await self._on_quick_pay(ctx, int(args[0]), args[1], int(args[2]))
            case "bills_add_done":                      return await self._on_done(ctx)
            case "bills_add_cancel":                    return await self._on_cancel(ctx)
            case "bills_add_confirm":                   return await self._on_confirm(ctx)
            case "bills_add_more":                      return await self._on_more(ctx)
            case "bills_name_pick" if args:             return await self._on_name_pick(ctx, args[0])
            case "bills_name_new":                      return await self._on_name_new(ctx)
            case "bills_q_pick" if args:                return await self._on_q_pick(ctx, int(args[0]))
            case "bills_change_list":                    return await self._on_change_list(ctx)
            case "bills_change_back":                    return await self._on_change_back(ctx)
            case "bills_chg" if args:                    return await self._on_change_pick(ctx, int(args[0]))
            case "bills_chgp" if len(args) >= 2:         return await self._on_change_choose(ctx, int(args[0]), args[1])
            case "bills_chgn" if args:                   return await self._on_change_new(ctx, int(args[0]))
            case "bills_noop":                           return True
            case "bills_suggest_start" if args:         return await self._on_suggest_start(ctx, int(args[0]))
            case "bills_suggest_approve" if args:       return await self._on_suggest_decide(ctx, args[0], approve=True)
            case "bills_suggest_reject" if args:        return await self._on_suggest_decide(ctx, args[0], approve=False)
            case "bills_suggest_skip":                  return True
            case "bills_pay_confirm" if args:           return await self._on_pay_decide(ctx, args[0], confirm=True)
            case "bills_pay_reject" if args:            return await self._on_pay_decide(ctx, args[0], confirm=False)
        return False

    def help(self):
        return "/bills — управление совместными расходами"

    def prompt(self):
        return (
            "/bills: создание и управление совместными расходами, "
            "добавление позиций в счёт, распознавание чеков по фото, "
            "регистрация платежей, просмотр долгов"
        )

    # ── Commands ──────────────────────────────────────────────────────────────

    async def _cmd_list(self, ctx: ChatBotContext, all_mode=False) -> bool:
        tid = ctx.message.from_user.id
        person, is_admin, bills = self._person_bills(tid, all_mode)
        logger.info("/bills list: tid=%s person=%s is_admin=%s bills=%d", tid, person.id if person else None, is_admin, len(bills))
        if not bills:
            await ctx.message.reply_text("У тебя пока нет счетов. Создай первый: /bills add <название>")
            return True

        by_id = self._persons()
        text = fmt.format_overview(bills, person.id if person else None, by_id, self.repository.db.bill_payments_v2)
        if all_mode:
            text += "\n_(режим: все чаты)_"

        open_bills = [b for b in bills if not b.closed]
        bill_buttons = [InlineKeyboardButton(f"#{b.id} {b.name[:18]}", callback_data=f"bills_view|{b.id}")
                        for b in open_bills]
        rows = fmt.compact_grid(bill_buttons, max_cols=2, max_rows=10)
        rows.append([InlineKeyboardButton("➕ Новый счёт", callback_data="bills_new")])
        await ctx.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return True

    async def _cmd_view(self, ctx: ChatBotContext, bill_id: int) -> bool:
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.message.reply_text(f"Счёт \\#{bill_id} не найден.")
            return True
        tid = ctx.message.from_user.id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        pid = person.id if person else None
        if not is_admin and pid not in (bill.participants + [bill.author_person_id]):
            await ctx.message.reply_text("Нет доступа к этому счёту.")
            return True
        by_id = self._persons()
        payments = self.repository.db.bill_payments_v2
        await ctx.message.reply_text(
            fmt.format_bill_detail(bill, pid, by_id, payments),
            parse_mode="Markdown",
            reply_markup=fmt.kb_bill(bill, pid, is_admin, payments),
        )
        return True

    async def _cmd_add(self, ctx: ChatBotContext, name: str) -> bool:
        tid, chat_id = ctx.message.from_user.id, ctx.message.chat_id
        if not name:
            self._s[(tid, chat_id)] = _Session(phase="naming", bill_name="", origin_chat_id=chat_id, caller_tid=tid)
            await ctx.message.reply_text("Как назовём счёт? Пришли название:")
            return True
        s = _Session(phase="collect", bill_name=name, origin_chat_id=chat_id, caller_tid=tid)
        self._s[(tid, chat_id)] = s
        await self._reply(ctx, f"Создаём счёт «{name}».\n\nОтправляй фото чеков, голосовые или текст. Когда готово — жми «Готово».", s=s, reply_markup=fmt.kb_collect())
        return True

    async def _cmd_pay(self, ctx: ChatBotContext, args: str) -> bool:
        m = re.match(r"([\d.,]+)\s*@?(\S+)", args.strip())
        if not m:
            await ctx.message.reply_text("Формат: /bills pay 100 @username\nили: /bills pay 50.50 Имя")
            return True
        try:
            amount_minor = minor_from_float(float(m.group(1).replace(",", ".")))
        except ValueError:
            await ctx.message.reply_text("Неверная сумма.")
            return True
        return await self._create_payment(ctx, ctx.message.from_user, amount_minor, m.group(2), ctx.message.chat_id)

    async def _cmd_alias(self, ctx: ChatBotContext, args: str) -> bool:
        if not args:
            await ctx.message.reply_text("Формат: /bills alias Лёша = Алексей")
            return True
        m = re.match(r"(.+?)\s*=\s*(.+)", args)
        if not m:
            await ctx.message.reply_text("Формат: /bills alias Имя = Псевдоним")
            return True
        target_name, alias = m.group(1).strip(), m.group(2).strip()
        person, candidates = match_name(target_name, self.repository.db.bill_persons, self._users(),
                                        caller_telegram_id=ctx.message.from_user.id,
                                        origin_chat_id=ctx.message.chat_id)
        if not person:
            msg = f"Несколько совпадений для «{target_name}»." if candidates else f"«{target_name}» не найден."
            await ctx.message.reply_text(msg)
            return True
        new_aliases = [a.strip() for a in re.split(r"[,\s]+", alias) if a.strip()]
        added = [a for a in new_aliases if a not in person.aliases]
        person.aliases.extend(added)
        if added:
            await self.repository.save()
        await ctx.message.reply_text(f"✅ Добавлено {len(added)} псевдонимов для {person.display_name}: {', '.join(added)}")
        return True

    async def _cmd_notify(self, ctx: ChatBotContext, args: str) -> bool:
        prefs = self.repository.get_bill_notification_prefs(ctx.message.from_user.id)
        if not args:
            await ctx.message.reply_text(
                f"⚙️ Тихий режим: {prefs.quiet_start}:00–{prefs.quiet_end}:00\n\n"
                f"Изменить: /bills notify quiet 22 8\nОтключить: /bills notify quiet 0 24")
            return True
        m = re.match(r"quiet\s+(\d+)\s+(\d+)", args)
        if m:
            qs, qe = int(m.group(1)), int(m.group(2))
            if 0 <= qs <= 23 and 0 <= qe <= 24:
                prefs.quiet_start, prefs.quiet_end = qs, qe
                await self.repository.save()
                await ctx.message.reply_text(f"✅ Тихий режим: {qs}:00–{qe}:00")
            else:
                await ctx.message.reply_text("Часы: 0–23 (начало), 0–24 (конец).")
        return True

    async def _cmd_help(self, ctx: ChatBotContext) -> bool:
        await ctx.message.reply_text(
            "📖 *Справка /bills*\n\n"
            "/bills — список счетов и долги\n"
            "/bills add <название> — создать счёт\n"
            "/bills <id> — посмотреть счёт\n"
            "/bills pay <сумма> @user — зарегистрировать платёж\n"
            "/bills alias <имя> = <псевдоним> — добавить псевдоним\n"
            "/bills notify — настройки уведомлений\n"
            "/bills all — все счета (админ)",
            parse_mode="Markdown")
        return True

    # ── Session input ─────────────────────────────────────────────────────────

    async def _on_input(self, ctx: ChatBotContext, s: _Session) -> bool:
        msg = ctx.message
        match s.phase:
            case "naming":
                if msg.text and not msg.text.startswith("/"):
                    s.bill_name = msg.text.strip()
                    s.phase = "collect"
                    await self._reply(ctx, f"Создаём счёт «{s.bill_name}».\n\nОтправляй фото, голосовые или текст.", s=s, reply_markup=fmt.kb_collect())
            case "collect":
                return await self._collect(ctx, s)
            case "questions" | "answering":
                return await self._answer_question(ctx, s)
            case "resolve":
                return await self._resolve_text(ctx, s)
            case "paying":
                return await self._collect_payment(ctx, s)
        return True

    async def _collect(self, ctx: ChatBotContext, s: _Session) -> bool:
        msg = ctx.message
        if msg.photo:
            await msg.reply_text("⏳ Распознаю фото...")
            text = await media.ocr_photo(ctx, msg.photo[-1])
            if text:
                s.context_items.append(f"[Фото]\n{text}")
                await self._reply(ctx, "✅ Фото добавлено.", s=s, reply_markup=fmt.kb_collect(s.context_items))
            else:
                await self._reply(ctx, "Не удалось распознать фото.", s=s, reply_markup=fmt.kb_collect(s.context_items))
        elif msg.voice:
            await msg.reply_text("⏳ Расшифровываю голосовое...")
            text = await media.transcribe_voice(ctx, msg.voice)
            if text:
                s.context_items.append(f"[Голосовое]\n{text}")
                await self._reply(ctx, "✅ Голосовое добавлено.", s=s, reply_markup=fmt.kb_collect(s.context_items))
            else:
                await self._reply(ctx, "Не удалось расшифровать.", s=s, reply_markup=fmt.kb_collect(s.context_items))
        elif msg.text and not msg.text.startswith("/"):
            s.context_items.append(f"[Текст]\n{msg.text.strip()}")
            await self._reply(ctx, "✅ Текст добавлен.", s=s, reply_markup=fmt.kb_collect(s.context_items))
        return True

    async def _answer_question(self, ctx: ChatBotContext, s: _Session) -> bool:
        msg = ctx.message
        if not (msg.text and not msg.text.startswith("/")):
            return True
        if not s.question_queue:
            return True
        q = s.question_queue.pop(0)
        s.context_items.append(f"[Ответ на «{q['text']}»] {msg.text.strip()}")
        await self._reply(ctx, f"✓ записал: {msg.text.strip()}", s=s)
        await self._next_question(ctx, s)
        return True

    async def _collect_payment(self, ctx: ChatBotContext, s: _Session) -> bool:
        msg = ctx.message
        if not msg.text or msg.text.startswith("/"):
            return True
        m = re.match(r"([\d.,]+)\s+@?(\S.*)", msg.text.strip())
        if not m:
            await msg.reply_text("Формат: «сумма @username» или «сумма Имя».")
            return True
        try:
            amount_minor = minor_from_float(float(m.group(1).replace(",", ".")))
        except ValueError:
            await msg.reply_text("Неверная сумма.")
            return True
        await self._create_payment(ctx, msg.from_user, amount_minor, m.group(2).strip(), s.origin_chat_id,
                                   bill_id=s.target_bill_id)
        self._s.pop(self._key(ctx), None)
        return True

    async def _resolve_text(self, ctx: ChatBotContext, s: _Session) -> bool:
        """Handle text input during resolve phase: @username or name."""
        msg = ctx.message
        if not (msg.text and not msg.text.startswith("/")):
            return True
        if not s.resolve_queue:
            return True
        text = msg.text.strip()
        raw_name = s.resolve_queue[0][0]
        key = parse.norm_name_key(raw_name)
        person = None

        if text.startswith("@"):
            username = text.lstrip("@")
            person = self.repository.get_bill_person_by_username(username)
            if not person:
                real_user = next((u for u in self.repository.db.users if getattr(u, 'username', None) == username), None)
                if real_user:
                    person, _ = self.repository.get_or_create_bill_person(
                        telegram_id=real_user.id, display_name=real_user.name or username, username=username)
            if not person:
                person, _ = self.repository.get_or_create_anonymous_person(f"@{username}")
        else:
            all_persons = self.repository.db.bill_persons
            person, _ = match_name(text, all_persons, self._users(), caller_telegram_id=s.caller_tid, origin_chat_id=s.origin_chat_id)
            if not person:
                person, _ = self.repository.get_or_create_anonymous_person(text)

        s.resolve_queue.pop(0)
        s.resolved_map[key] = person.id
        await (self._next_disambiguation(ctx, s) if s.resolve_queue else self._show_preview(ctx, s))
        return True

    # ── AI parse pipeline ─────────────────────────────────────────────────────

    async def _run_ai(self, ctx, s: _Session) -> bool:
        if not s.context_items:
            await self._reply(ctx, "Нет данных для анализа. Добавь фото, голосовое или текст.", s=s)
            return False

        caller = self.repository.get_bill_person_by_telegram_id(s.caller_tid)
        caller_name = caller.display_name if caller else None
        context_text = "\n\n".join(s.context_items)
        if caller_name:
            context_text = f"Я = {caller_name}\n\n" + context_text

        chat_persons = self._chat_persons(s.caller_tid)
        prompt_input = f"{parse.build_persons_directory(chat_persons)}\n\n---\n\n{context_text}"

        try:
            ai_response = await make_openrouter_query(
                user_id=f"bills_ocr_{s.caller_tid}",
                model=OpenRouterModel.GEMINI_25_FLASH,
                messages=[("user", prompt_input)],
                system_prompt=_bill_ocr_prompt(),
                max_tokens=4096,
                timeout_seconds=60.0,
            )
        except TimeoutError:
            logger.warning("AI OCR timed out for user %s", s.caller_tid)
            await self._reply(ctx, "⏱ AI не ответил вовремя. Попробуй ещё раз.", s=s, reply_markup=fmt.kb_collect(s.context_items))
            return False
        except Exception as e:
            logger.exception("AI OCR failed: %s", e)
            await self._reply(ctx, f"Ошибка AI: {e}", s=s)
            return False

        currency, rows, new_persons, questions = parse.parse_ai_response(ai_response)
        s.currency = currency
        s.new_person_names = new_persons
        s.question_queue = list(questions)

        if not rows and not questions:
            await self._reply(ctx, "AI не нашёл позиций. Попробуй добавить ещё данных.", s=s, reply_markup=fmt.kb_collect(s.context_items))
            return False

        # Resolve names: match against ALL persons, use chat_persons only for disambiguation UI
        all_raw: list[str] = []
        for row in rows:
            if row["creditor_raw"] not in ("", "-"):
                all_raw.append(row["creditor_raw"].strip())
            for n in row["debtors_raw"].split(","):
                n = n.strip()
                if n and n != "-":
                    all_raw.append(n)

        seen: dict[str, str] = {}
        for raw in all_raw:
            key = parse.norm_name_key(raw)
            if key not in seen:
                seen[key] = raw

        users = self._users()
        all_persons = self.repository.db.bill_persons
        resolve_queue = []
        resolved = dict(s.resolved_map)

        for key, raw in seen.items():
            if key in resolved:
                continue
            person, candidates = match_name(raw, all_persons, users, caller_telegram_id=s.caller_tid, origin_chat_id=s.origin_chat_id)
            if person and person.telegram_id:
                resolved[key] = person.id
            elif candidates:
                resolve_queue.append((raw, candidates))
            else:
                resolve_queue.append((raw, chat_persons))

        s.resolve_queue = resolve_queue
        s.resolved_map = resolved
        s.parsed_rows = rows
        return True

    async def _next_question(self, ctx, s: _Session):
        if not s.question_queue:
            await self._reply(ctx, "⏳ Пересчитываю...", s=s)
            ok = await self._run_ai(ctx, s)
            if not ok:
                return
            if s.question_queue:
                return await self._next_question(ctx, s)
            if s.resolve_queue:
                return await self._next_disambiguation(ctx, s)
            return await self._show_preview(ctx, s)

        s.phase = "questions"
        q = s.question_queue[0]
        option_buttons = [InlineKeyboardButton(opt, callback_data=f"bills_q_pick|{i}")
                          for i, opt in enumerate(q["options"])]
        rows = fmt.compact_grid(option_buttons, max_cols=3)
        await self._reply(ctx, f"❓ {q['text']}", s=s, reply_markup=InlineKeyboardMarkup(rows))

    async def _next_disambiguation(self, ctx, s: _Session):
        if not s.resolve_queue:
            return await self._show_preview(ctx, s)
        s.phase = "resolve"
        raw_name, candidates = s.resolve_queue[0]
        chat_persons = self._chat_persons(s.caller_tid)
        is_unknown = len(candidates) == len(chat_persons)
        if is_unknown:
            text = f"Не знаю кто такой «{raw_name}».\n_Выбери из знакомых, напиши @тег или имя_"
        else:
            names = ", ".join(p.display_name for p in candidates[:3])
            text = f"«{raw_name}» — это {names}?\n_Или напиши @тег / имя_"
        await self._reply(ctx, text, s=s, reply_markup=fmt.kb_disambiguation(candidates))

    async def _show_preview(self, ctx, s: _Session):
        for name in s.new_person_names:
            key = parse.norm_name_key(name)
            if key not in s.resolved_map or s.resolved_map[key] == UNKNOWN_PERSON_ID:
                person, _ = self.repository.get_or_create_anonymous_person(name)
                s.resolved_map[key] = person.id

        s.parsed_transactions = parse.rows_to_transactions(s.parsed_rows, s.resolved_map)
        s.phase = "confirm"
        text = fmt.format_preview(s.parsed_transactions, self._persons(), s.currency, s.resolved_map)
        await self._reply(ctx, text, s=s, reply_markup=fmt.kb_confirm())

    # ── Save ────────────────────────────────────────────────────────────────���─

    async def _save_bill(self, ctx, s: _Session):
        user = self._user(ctx)
        caller, _ = self.repository.get_or_create_bill_person(
            telegram_id=s.caller_tid,
            display_name=user.full_name or str(s.caller_tid),
            username=user.username,
        )

        participant_ids = [caller.id]
        for tx in s.parsed_transactions:
            for asg in tx.assignments:
                for d in asg.debtors:
                    if d and d not in participant_ids:
                        participant_ids.append(d)
            if tx.creditor and tx.creditor not in participant_ids:
                participant_ids.append(tx.creditor)
        participants = [p for p in participant_ids if p != UNKNOWN_PERSON_ID]

        bill = BillV2(
            id=self.repository.get_next_bill_v2_id(),
            name=s.bill_name,
            author_person_id=caller.id,
            participants=participants,
            transactions=s.parsed_transactions,
            currency=s.currency,
            origin_chat_id=s.origin_chat_id,
            updated_at=datetime.now(),
        )
        self.repository.db.bills_v2.append(bill)

        by_id = self._persons()
        for pid in participants:
            if p := by_id.get(pid):
                update_chat_last_seen(p, s.origin_chat_id)

        if any(tx.incomplete for tx in s.parsed_transactions):
            from steward.delayed_action.bill_incomplete_nudge import schedule_incomplete_nudge
            schedule_incomplete_nudge(self.repository, bill.id)

        await self.repository.save()
        self._s.pop(self._key(ctx), None)

        by_id = self._persons()
        text = fmt.format_bill_created(bill, by_id)
        kb = fmt.kb_bill(bill, caller.id, self.repository.is_admin(s.caller_tid), self.repository.db.bill_payments_v2)
        await self._reply(ctx, text, reply_markup=kb)

    async def _save_suggestion(self, ctx, s: _Session):
        bill = self.repository.get_bill_v2(s.target_bill_id)
        if not bill or bill.closed:
            await self._reply(ctx, "Счёт больше недоступен.")
            self._s.pop(self._key(ctx), None)
            return

        user = self._user(ctx)
        proposer = self.repository.get_bill_person_by_telegram_id(s.caller_tid)
        if not proposer:
            proposer, _ = self.repository.get_or_create_bill_person(
                telegram_id=s.caller_tid, display_name=user.full_name or str(s.caller_tid), username=user.username)

        suggestion = BillItemSuggestion(
            id=str(uuid.uuid4()),
            bill_id=bill.id,
            proposed_by_person_id=proposer.id,
            proposed_tx=s.parsed_transactions,
            origin_chat_id=s.origin_chat_id,
            bill_updated_at_propose=bill.updated_at,
        )
        self.repository.db.bill_item_suggestions.append(suggestion)

        author = self.repository.get_bill_person(bill.author_person_id)
        if author:
            lines = [f"🧾 {proposer.display_name} предлагает добавить в «{bill.name}» \\#{bill.id}:"]
            for tx in suggestion.proposed_tx[:5]:
                total = minor_to_display(tx.unit_price_minor * tx.quantity, bill.currency)
                lines.append(f"  • {tx.item_name} × {tx.quantity} — {total}")
            if len(suggestion.proposed_tx) > 5:
                lines.append(f"  … и ещё {len(suggestion.proposed_tx) - 5}")

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Одобрить", callback_data=f"bills_suggest_approve|{suggestion.id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"bills_suggest_reject|{suggestion.id}"),
            ]])
            msg = await send_bill_notification(
                ctx.bot, self.repository, author, "\n".join(lines),
                reply_markup=kb, initiated_chat_id=suggestion.origin_chat_id,
            )
            if msg:
                suggestion.approval_chat_id = msg.chat_id
                suggestion.approval_message_id = msg.message_id

        from steward.delayed_action.bill_suggestion_lifecycle import schedule_suggestion_lifecycle
        schedule_suggestion_lifecycle(self.repository, suggestion.id)

        await self.repository.save()
        self._s.pop(self._key(ctx), None)
        await self._reply(ctx, f"📤 Предложение отправлено автору «{bill.name}».")

    # ── Payment creation ──────────────────────────────────────────────────────

    def _find_bill_ids_for_pair(self, debtor_id: str, creditor_id: str) -> list[int]:
        """Find all open bills where debtor owes creditor."""
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

    async def _register_payment(self, ctx, debtor, creditor, amount_minor: int, currency: str, chat_id: int, bill_ids: list[int] | None = None):
        """Create payment, notify creditor immediately, schedule reminder."""
        all_bill_ids = bill_ids if bill_ids else self._find_bill_ids_for_pair(debtor.id, creditor.id)
        payment = BillPaymentV2(
            id=str(uuid.uuid4()), debtor=debtor.id, creditor=creditor.id,
            amount_minor=amount_minor, currency=currency,
            status=PaymentStatus.PENDING, initiated_chat_id=chat_id,
            bill_ids=all_bill_ids,
        )
        self.repository.db.bill_payments_v2.append(payment)

        from steward.delayed_action.bill_payment_reminder import schedule_payment_reminder
        schedule_payment_reminder(self.repository, payment.id)

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Получил", callback_data=f"bills_pay_confirm|{payment.id}"),
            InlineKeyboardButton("❌ Не получал", callback_data=f"bills_pay_reject|{payment.id}"),
        ]])
        amount_str = minor_to_display(amount_minor, currency)
        mention = f"[{creditor.display_name}](tg://user?id={creditor.telegram_id})" if creditor.telegram_id else creditor.display_name
        notif = await send_bill_notification(
            ctx.bot, self.repository, creditor,
            f"💸 {debtor.display_name} говорит, что перевёл {mention} *{amount_str}*\nПодтверди получение:",
            sender=debtor, reply_markup=kb, parse_mode="Markdown",
            initiated_chat_id=chat_id,
        )
        if notif:
            payment.confirmation_chat_id = notif.chat_id
            payment.confirmation_message_id = notif.message_id
        logger.info("Payment %s created: %s -> %s %s, notified=%s", payment.id[:8], debtor.display_name, creditor.display_name, amount_str, bool(notif))
        await self.repository.save()
        return payment

    async def _create_payment(self, ctx, from_user, amount_minor: int, target_name: str, chat_id: int, *, bill_id: int | None = None):
        debtor, _ = self.repository.get_or_create_bill_person(
            telegram_id=from_user.id,
            display_name=from_user.full_name or str(from_user.id),
            username=from_user.username,
        )
        creditor, candidates = match_name(
            target_name.lstrip("@"), self.repository.db.bill_persons, self._users(),
            caller_telegram_id=from_user.id, origin_chat_id=chat_id,
        )
        if not creditor:
            if candidates:
                await self._reply(ctx, f"«{target_name}» неоднозначно: {', '.join(p.display_name for p in candidates[:5])}.")
            else:
                await self._reply(ctx, f"Не нашёл «{target_name}».")
            return True

        currency = (self.repository.get_bill_v2(bill_id).currency if bill_id else None) or "BYN"

        await self._register_payment(ctx, debtor, creditor, amount_minor, currency, chat_id)
        await self._reply(ctx, f"💸 Платёж {minor_to_display(amount_minor, currency)} → {creditor.display_name} зарегистрирован. Ждём подтверждения.")
        return True

    # ── Callbacks ─────────────────────────────────────────────────────────────

    async def _on_list(self, ctx: CallbackBotContext, closed: bool) -> bool:
        tid = ctx.callback_query.from_user.id
        person, is_admin, bills = self._person_bills(tid)
        logger.info("_on_list: tid=%s person=%s bills=%d closed=%s", tid, person.id if person else None, len(bills), closed)
        filtered = [b for b in bills if b.closed == closed]
        if not filtered:
            await ctx.callback_query.message.edit_text("Нет закрытых счетов." if closed else "Нет открытых счетов.")
            return True
        bill_buttons = [InlineKeyboardButton(f"#{b.id} {b.name[:18]}", callback_data=f"bills_view|{b.id}")
                        for b in filtered]
        rows = fmt.compact_grid(bill_buttons, max_cols=2, max_rows=10)
        if not closed:
            rows.append([InlineKeyboardButton("➕ Новый", callback_data="bills_new")])
        label = "📕 *Закрытые счета:*" if closed else "📋 *Открытые счета:*"
        await ctx.callback_query.message.edit_text(label, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return True

    async def _on_new(self, ctx: CallbackBotContext) -> bool:
        tid = ctx.callback_query.from_user.id
        chat_id = ctx.callback_query.message.chat_id
        self._s.pop((tid, chat_id), None)
        self._s[(tid, chat_id)] = _Session(phase="naming", bill_name="", origin_chat_id=chat_id, caller_tid=tid)
        try:
            await ctx.callback_query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await ctx.callback_query.message.reply_text("Как назовём счёт? Пришли название одним сообщением.")
        return True

    async def _on_view(self, ctx: CallbackBotContext, bill_id: int) -> bool:
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.callback_query.message.edit_text(f"Счёт \\#{bill_id} не найден.")
            return True
        tid = ctx.callback_query.from_user.id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        pid = person.id if person else None
        logger.info("_on_view: tid=%s pid=%s bill=%d author=%s participants=%s", tid, pid, bill_id, bill.author_person_id, bill.participants)
        if not is_admin and pid not in (bill.participants + [bill.author_person_id]):
            await ctx.callback_query.answer("Нет доступа.", show_alert=True)
            return True
        by_id = self._persons()
        payments = self.repository.db.bill_payments_v2
        await ctx.callback_query.message.edit_text(
            fmt.format_bill_detail(bill, pid, by_id, payments),
            parse_mode="Markdown",
            reply_markup=fmt.kb_bill(bill, pid, is_admin, payments),
        )
        return True

    async def _on_close(self, ctx: CallbackBotContext, bill_id: int, close: bool) -> bool:
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.callback_query.answer("Счёт не найден.", show_alert=True)
            return True
        tid = ctx.callback_query.from_user.id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        if not is_admin and (not person or person.id != bill.author_person_id):
            await ctx.callback_query.answer("Нет прав.", show_alert=True)
            return True

        bill.closed = close
        bill.closed_at = datetime.now() if close else None
        await self.repository.save()

        if close:
            # Warn about unsettled debts
            from steward.helpers.bills_money import compute_bill_debts, net_debts, apply_payments
            raw = compute_bill_debts(bill.transactions, bill.currency)
            net = net_debts(raw)
            bp = [p for p in self.repository.db.bill_payments_v2 if bill.id in p.bill_ids]
            after = apply_payments(net, bp, clamp_zero=True)
            has_debts = any(a > 0 for creds in after.values() for a in creds.values())
            msg = f"🔒 Счёт «{bill.name}» закрыт."
            if has_debts:
                msg += "\n⚠️ Остались неоплаченные долги!"
            await ctx.callback_query.message.edit_text(msg)
        else:
            pid = person.id if person else None
            by_id = self._persons()
            payments = self.repository.db.bill_payments_v2
            await ctx.callback_query.message.edit_text(
                fmt.format_bill_detail(bill, pid, by_id, payments),
                parse_mode="Markdown",
                reply_markup=fmt.kb_bill(bill, pid, is_admin, payments),
            )
        return True

    async def _on_pay_start(self, ctx: CallbackBotContext, bill_id: int) -> bool:
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.callback_query.answer("Счёт не найден.", show_alert=True)
            return True
        tid = ctx.callback_query.from_user.id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        pid = person.id if person else None
        if not pid:
            await ctx.callback_query.answer("Ты не участник этого счёта.", show_alert=True)
            return True

        by_id = self._persons()
        payments = self.repository.db.bill_payments_v2
        text, kb = fmt.kb_pay_global(pid, by_id, self.repository.db.bills_v2, payments, bill.id)
        await ctx.callback_query.message.edit_text(text, reply_markup=kb)
        return True

    async def _on_pay_manual(self, ctx: CallbackBotContext, bill_id: int) -> bool:
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.callback_query.answer("Счёт не найден.", show_alert=True)
            return True
        tid = ctx.callback_query.from_user.id
        chat_id = ctx.callback_query.message.chat_id
        self._s.pop((tid, chat_id), None)
        self._s[(tid, chat_id)] = _Session(phase="paying", bill_name=bill.name, origin_chat_id=chat_id, caller_tid=tid, target_bill_id=bill.id)
        await ctx.callback_query.message.reply_text(
            f"💸 Оплата по «{bill.name}».\nПришли: «сумма @кому» или «сумма Имя».\n\nДля отмены: /stop",
        )
        return True

    async def _on_quick_pay(self, ctx: CallbackBotContext, bill_id: int, creditor_short: str, amount_minor: int) -> bool:
        bill = self.repository.get_bill_v2(bill_id)
        if not bill:
            await ctx.callback_query.answer("Счёт не найден.", show_alert=True)
            return True
        tid = ctx.callback_query.from_user.id
        debtor, _ = self.repository.get_or_create_bill_person(
            telegram_id=tid,
            display_name=ctx.callback_query.from_user.full_name or str(tid),
            username=ctx.callback_query.from_user.username,
        )
        # Find creditor by truncated ID prefix
        creditor = next((p for p in self.repository.db.bill_persons if p.id.startswith(creditor_short)), None)
        if not creditor:
            await ctx.callback_query.answer("Получатель не найден.", show_alert=True)
            return True

        chat_id = ctx.callback_query.message.chat_id
        await self._register_payment(ctx, debtor, creditor, amount_minor, bill.currency, chat_id)
        await ctx.callback_query.message.edit_text(
            f"💸 Платёж {minor_to_display(amount_minor, bill.currency)} → {creditor.display_name} зарегистрирован.\nЖдём подтверждения."
        )
        return True

    async def _on_done(self, ctx: CallbackBotContext) -> bool:
        tid = ctx.callback_query.from_user.id
        chat_id = ctx.callback_query.message.chat_id
        s = self._s.get((tid, chat_id))
        if not s or s.phase != "collect":
            await ctx.callback_query.answer("Нет активной сессии.", show_alert=True)
            return True
        if not s.context_items:
            await ctx.callback_query.answer("Сначала добавь данные!", show_alert=True)
            return True

        await self._reply(ctx, "⏳ Анализирую данные...", s=s)

        ok = await self._run_ai(ctx, s)
        if not ok:
            return True
        if s.question_queue:
            await self._next_question(ctx, s)
        elif s.resolve_queue:
            await self._next_disambiguation(ctx, s)
        else:
            await self._show_preview(ctx, s)
        return True

    async def _on_cancel(self, ctx: CallbackBotContext) -> bool:
        self._s.pop(self._key(ctx), None)
        await ctx.callback_query.message.edit_text("❌ Отменено.")
        return True

    async def _on_confirm(self, ctx: CallbackBotContext) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or s.phase != "confirm":
            await ctx.callback_query.answer("Нет активной сессии.", show_alert=True)
            return True
        if s.is_suggestion:
            await self._save_suggestion(ctx, s)
        else:
            await self._save_bill(ctx, s)
        return True

    async def _on_more(self, ctx: CallbackBotContext) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or s.phase not in ("confirm", "resolve"):
            await ctx.callback_query.answer("Нет активной сессии.", show_alert=True)
            return True
        s.phase = "collect"
        s.parsed_transactions = []
        s.resolve_queue = []
        s.new_person_names = []
        s.parsed_rows = []
        await self._reply(ctx, "Давай ещё контекст. Пришли текст, фото или голосовое и нажми «Готово».", s=s, reply_markup=fmt.kb_collect(s.context_items))
        return True

    async def _on_name_pick(self, ctx: CallbackBotContext, person_id: str) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or not s.resolve_queue:
            return True
        raw_name = s.resolve_queue.pop(0)[0]
        s.resolved_map[parse.norm_name_key(raw_name)] = person_id
        await (self._next_disambiguation(ctx, s) if s.resolve_queue else self._show_preview(ctx, s))
        return True

    async def _on_name_new(self, ctx: CallbackBotContext) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or not s.resolve_queue:
            return True
        raw_name = s.resolve_queue.pop(0)[0]
        person, _ = self.repository.get_or_create_anonymous_person(raw_name)
        s.resolved_map[parse.norm_name_key(raw_name)] = person.id
        await (self._next_disambiguation(ctx, s) if s.resolve_queue else self._show_preview(ctx, s))
        return True

    async def _on_q_pick(self, ctx: CallbackBotContext, option_idx: int) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or not s.question_queue:
            await ctx.callback_query.answer("Нет активного вопроса.", show_alert=True)
            return True
        q = s.question_queue[0]
        options = q["options"]
        if option_idx < 0 or option_idx >= len(options):
            return True
        chosen = options[option_idx]

        if chosen.lower() == "другое":
            s.phase = "answering"
            await self._reply(ctx, f"❓ {q['text']}\n→ Напиши ответ одним сообщением.", s=s)
            return True

        s.question_queue.pop(0)
        s.context_items.append(f"[Ответ на «{q['text']}»] {chosen}")
        await self._next_question(ctx, s)
        return True

    async def _on_change_list(self, ctx: CallbackBotContext) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or s.phase != "confirm":
            await ctx.callback_query.answer("Нет активной сессии.", show_alert=True)
            return True
        by_id = self._persons()
        kb = fmt.kb_change_list(s.resolved_map, by_id)
        try:
            await ctx.callback_query.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
        return True

    async def _on_change_back(self, ctx: CallbackBotContext) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or s.phase != "confirm":
            await ctx.callback_query.answer("Нет активной сессии.", show_alert=True)
            return True
        try:
            await ctx.callback_query.message.edit_reply_markup(reply_markup=fmt.kb_confirm())
        except Exception:
            pass
        return True

    async def _on_change_pick(self, ctx: CallbackBotContext, idx: int) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or s.phase != "confirm":
            await ctx.callback_query.answer("Нет активной сессии.", show_alert=True)
            return True
        sorted_keys = sorted(s.resolved_map.keys())
        if idx < 0 or idx >= len(sorted_keys):
            return True
        raw_key = sorted_keys[idx]
        persons = self.repository.db.bill_persons
        kb = fmt.kb_change_pick(idx, persons)
        try:
            await ctx.callback_query.message.edit_text(
                f"Кто такой «{raw_key.title()}»?",
                reply_markup=kb,
            )
        except Exception:
            pass
        return True

    async def _on_change_choose(self, ctx: CallbackBotContext, idx: int, person_id: str) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or s.phase != "confirm":
            await ctx.callback_query.answer("Нет активной сессии.", show_alert=True)
            return True
        sorted_keys = sorted(s.resolved_map.keys())
        if idx < 0 or idx >= len(sorted_keys):
            return True
        raw_key = sorted_keys[idx]
        s.resolved_map[raw_key] = person_id
        s.parsed_transactions = parse.rows_to_transactions(s.parsed_rows, s.resolved_map)
        person = self.repository.get_bill_person(person_id)
        by_id = self._persons()
        text = fmt.format_preview(s.parsed_transactions, by_id, s.currency, s.resolved_map)
        try:
            await ctx.callback_query.message.edit_text(text, reply_markup=fmt.kb_confirm())
        except Exception:
            pass
        s.last_kb_msg = ctx.callback_query.message.message_id
        s.last_kb_chat = ctx.callback_query.message.chat_id
        return True

    async def _on_change_new(self, ctx: CallbackBotContext, idx: int) -> bool:
        s = self._s.get(self._key(ctx))
        if not s or s.phase != "confirm":
            await ctx.callback_query.answer("Нет активной сессии.", show_alert=True)
            return True
        sorted_keys = sorted(s.resolved_map.keys())
        if idx < 0 or idx >= len(sorted_keys):
            return True
        raw_key = sorted_keys[idx]
        person, _ = self.repository.get_or_create_anonymous_person(raw_key.title())
        s.resolved_map[raw_key] = person.id
        s.parsed_transactions = parse.rows_to_transactions(s.parsed_rows, s.resolved_map)
        by_id = self._persons()
        text = fmt.format_preview(s.parsed_transactions, by_id, s.currency, s.resolved_map)
        try:
            await ctx.callback_query.message.edit_text(text, reply_markup=fmt.kb_confirm())
        except Exception:
            pass
        s.last_kb_msg = ctx.callback_query.message.message_id
        s.last_kb_chat = ctx.callback_query.message.chat_id
        return True

    async def _on_suggest_start(self, ctx: CallbackBotContext, bill_id: int) -> bool:
        bill = self.repository.get_bill_v2(bill_id)
        if not bill or bill.closed:
            await ctx.callback_query.message.edit_text("Счёт закрыт или не найден.")
            return True
        tid = ctx.callback_query.from_user.id
        chat_id = ctx.callback_query.message.chat_id
        s = _Session(phase="collect", bill_name=bill.name, origin_chat_id=chat_id, caller_tid=tid, is_suggestion=True, target_bill_id=bill_id)
        self._s[(tid, chat_id)] = s
        await ctx.callback_query.message.edit_text(
            f"Предложение для «{bill.name}».\nОтправляй фото, голосовые или текст.",
            reply_markup=fmt.kb_collect(),
        )
        return True

    async def _on_suggest_decide(self, ctx: CallbackBotContext, suggestion_id: str, approve: bool) -> bool:
        suggestion = self.repository.get_bill_suggestion(suggestion_id)
        if not suggestion or suggestion.status != SuggestionStatus.PENDING:
            await ctx.callback_query.answer("Предложение уже обработано.", show_alert=True)
            return True
        bill = self.repository.get_bill_v2(suggestion.bill_id)
        if not bill:
            await ctx.callback_query.answer("Счёт не найден.", show_alert=True)
            return True
        tid = ctx.callback_query.from_user.id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        if not is_admin and (not person or person.id != bill.author_person_id):
            await ctx.callback_query.answer("Нет прав.", show_alert=True)
            return True

        if approve:
            if suggestion.bill_updated_at_propose and bill.updated_at != suggestion.bill_updated_at_propose:
                await ctx.callback_query.answer("Счёт изменился. Проверь вручную.", show_alert=True)
                return True
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
                ctx.bot, self.repository, proposer,
                f"{emoji} Твоё предложение в «{bill.name}» {verb}.",
                initiated_chat_id=suggestion.origin_chat_id,
            )

        await self.repository.save()
        if approve:
            await ctx.callback_query.message.edit_text(f"✅ Одобрено, {len(suggestion.proposed_tx)} позиций добавлено в «{bill.name}».")
        else:
            await ctx.callback_query.message.edit_text("❌ Предложение отклонено.")
        return True

    async def _on_pay_decide(self, ctx: CallbackBotContext, payment_id: str, confirm: bool) -> bool:
        payment = self.repository.get_bill_payment_v2(payment_id)
        if not payment or payment.status != PaymentStatus.PENDING:
            await ctx.callback_query.answer("Платёж уже обработан.", show_alert=True)
            return True
        tid = ctx.callback_query.from_user.id
        creditor = self.repository.get_bill_person(payment.creditor)
        is_admin = self.repository.is_admin(tid)
        if not is_admin and (not creditor or creditor.telegram_id != tid):
            await ctx.callback_query.answer("Только получатель может ответить.", show_alert=True)
            return True

        payment.status = PaymentStatus.CONFIRMED if confirm else PaymentStatus.REJECTED

        if confirm:
            debtor = self.repository.get_bill_person(payment.debtor)
            name = debtor.display_name if debtor else "?"
            msg = f"✅ Получение {minor_to_display(payment.amount_minor, payment.currency)} от {name} подтверждено."

            # Auto-close bills if all debts settled
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

            await ctx.callback_query.message.edit_text(msg)
        else:
            await ctx.callback_query.message.edit_text("❌ Получение не подтверждено.")

        await self.repository.save()
        return True
