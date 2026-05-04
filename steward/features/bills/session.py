"""Custom Step driving the entire /bills creation/editing state machine.

Phases: naming → collect → questions/answering → resolve → confirm.
The 'paying' phase is handled by a separate _PayingStep.

The Step also handles all callback dispatching for in-session keyboards because
the session_handler intercepts callbacks before they reach the Feature's @on_callback
handlers. See architecture notes in BillsFeature.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from steward.data.models.bill_v2 import UNKNOWN_PERSON_ID
from steward.framework import Keyboard
from steward.helpers.ai import OpenRouterModel, get_prompt, make_openrouter_query
from steward.helpers.bills_money import minor_from_float
from steward.helpers.bills_person_match import match_name
from steward.session.context import CallbackStepContext, ChatStepContext
from steward.session.step import Step

from . import fmt, media, parse

if TYPE_CHECKING:
    from steward.features.bills import BillsFeature

logger = logging.getLogger(__name__)


def _bill_ocr_prompt() -> str:
    return get_prompt("bill_ocr")


def _bill_correct_prompt() -> str:
    return get_prompt("bill_correct")


@dataclass
class _SessionState:
    """Shared mutable state between the Step and BillsFeature.

    Phases: naming | collect | questions | answering | resolve | confirm.
    """
    phase: str
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
    announced: bool = False


class _BillCollectStep(Step):
    """Drives the entire bill-creation state machine through chat() and callback()."""

    def __init__(self):
        pass

    def _state(self, context) -> _SessionState | None:
        return context.session_context.get("state")

    def _feature(self, context) -> "BillsFeature":
        return context.session_context["_feature"]

    async def _send(
        self,
        context,
        text: str,
        *,
        keyboard: Keyboard | None = None,
        edit: bool | None = None,
    ):
        st = self._state(context)
        is_cb = isinstance(context, CallbackStepContext)
        markup = keyboard.to_markup() if keyboard is not None else None

        should_edit = edit if edit is not None else is_cb
        if should_edit:
            target = None
            if st and st.last_kb_msg and st.last_kb_chat:
                target = (st.last_kb_chat, st.last_kb_msg)
            elif is_cb:
                target = (
                    context.callback_query.message.chat_id,
                    context.callback_query.message.message_id,
                )
            if target is not None:
                try:
                    msg = await context.bot.edit_message_text(
                        text,
                        chat_id=target[0],
                        message_id=target[1],
                        reply_markup=markup,
                        parse_mode="Markdown",
                    )
                    if st:
                        if markup:
                            st.last_kb_msg, st.last_kb_chat = msg.message_id, msg.chat_id
                        else:
                            st.last_kb_msg = st.last_kb_chat = None
                    return msg
                except Exception as e:
                    logger.debug("edit failed: %s", e)

        if st and st.last_kb_msg and st.last_kb_chat:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=st.last_kb_chat,
                    message_id=st.last_kb_msg,
                    reply_markup=None,
                )
            except Exception:
                pass
            st.last_kb_msg = st.last_kb_chat = None

        chat_id = (
            context.callback_query.message.chat_id
            if is_cb
            else context.message.chat_id
        )
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode="Markdown",
        )
        if st:
            st.last_kb_msg, st.last_kb_chat = msg.message_id, msg.chat_id
        return msg

    async def chat(self, context: ChatStepContext) -> bool:
        st = self._state(context)
        if st is None:
            return True
        msg = context.message
        if msg is None:
            return False
        feature = self._feature(context)

        if not st.announced:
            st.announced = True
            if st.phase == "naming":
                cancel_kb = Keyboard.row(
                    feature.cb("bills:add_cancel").button("❌ Отмена")
                )
                await self._send(
                    context, "Как назовём счёт? Пришли название:",
                    keyboard=cancel_kb, edit=False,
                )
                return False
            if st.phase == "collect":
                kb = fmt.kb_collect(feature, st.context_items)
                if st.is_suggestion:
                    text = f"Предложение для «{st.bill_name}».\nОтправляй фото, голосовые или текст."
                else:
                    text = (
                        f"Создаём счёт «{st.bill_name}».\n\n"
                        "Отправляй фото чеков, голосовые или текст. Когда готово — жми «Готово»."
                    )
                await self._send(context, text, keyboard=kb, edit=False)
                return False

        if st.phase == "naming":
            if msg.text and not msg.text.startswith("/"):
                st.bill_name = msg.text.strip()
                st.phase = "collect"
                kb = fmt.kb_collect(feature, st.context_items)
                await self._send(
                    context,
                    f"Создаём счёт «{st.bill_name}».\n\nОтправляй фото, голосовые или текст.",
                    keyboard=kb,
                    edit=False,
                )
            return False

        if st.phase == "collect":
            await self._collect(context, st, feature)
            return False

        if st.phase in ("questions", "answering"):
            await self._answer_question(context, st, feature)
            return False

        if st.phase == "resolve":
            await self._resolve_text(context, st, feature)
            return False

        if st.phase == "confirm":
            await self._handle_correction_input(context, st, feature)
            return False

        return False

    async def callback(self, context: CallbackStepContext) -> bool:
        st = self._state(context)
        if st is None:
            return True
        feature = self._feature(context)
        data = context.callback_query.data or ""

        try:
            await context.callback_query.answer()
        except Exception:
            pass

        action, args = _split_cb(data)

        if not st.announced:
            st.announced = True
            if st.phase == "naming":
                cancel_kb = Keyboard.row(
                    feature.cb("bills:add_cancel").button("❌ Отмена")
                )
                await self._send(
                    context, "Как назовём счёт? Пришли название одним сообщением.",
                    keyboard=cancel_kb, edit=False,
                )
                return False
            if st.phase == "collect":
                kb = fmt.kb_collect(feature, st.context_items)
                if st.is_suggestion:
                    text = f"Предложение для «{st.bill_name}».\nОтправляй фото, голосовые или текст."
                else:
                    text = (
                        f"Создаём счёт «{st.bill_name}».\n\n"
                        "Отправляй фото чеков, голосовые или текст. Когда готово — жми «Готово»."
                    )
                await self._send(context, text, keyboard=kb, edit=False)
                return False

        if action == "bills:add_done":
            return await self._on_done(context, st, feature)
        if action == "bills:add_cancel":
            await self._on_cancel(context)
            return True
        if action == "bills:add_confirm":
            await self._on_confirm(context, st, feature)
            return True
        if action == "bills:add_more":
            await self._on_more(context, st, feature)
            return False
        if action == "bills:name_pick" and args:
            await self._on_name_pick(context, st, feature, args[0])
            return False
        if action == "bills:name_new":
            await self._on_name_new(context, st, feature)
            return False
        if action == "bills:q_pick" and args:
            await self._on_q_pick(context, st, feature, int(args[0]))
            return False
        if action == "bills:change_list":
            await self._on_change_list(context, st, feature)
            return False
        if action == "bills:change_back":
            await self._on_change_back(context, st, feature)
            return False
        if action == "bills:chg" and args:
            await self._on_change_pick(context, st, feature, int(args[0]))
            return False
        if action == "bills:chgp" and len(args) >= 2:
            await self._on_change_choose(context, st, feature, int(args[0]), args[1])
            return False
        if action == "bills:chgn" and args:
            await self._on_change_new(context, st, feature, int(args[0]))
            return False
        if action == "bills:noop":
            return False

        return False

    def stop(self):
        pass

    async def _collect(self, context: ChatStepContext, st: _SessionState, feature: "BillsFeature"):
        msg = context.message
        if msg.photo:
            await context.bot.send_message(chat_id=msg.chat_id, text="⏳ Распознаю фото...")
            text = await media.ocr_photo(context.bot, msg.photo[-1])
            kb = fmt.kb_collect(feature, st.context_items)
            if text:
                st.context_items.append(f"[Фото]\n{text}")
                kb = fmt.kb_collect(feature, st.context_items)
                await self._send(context, "✅ Фото добавлено.", keyboard=kb, edit=False)
            else:
                await self._send(context, "Не удалось распознать фото.", keyboard=kb, edit=False)
        elif msg.voice:
            await context.bot.send_message(chat_id=msg.chat_id, text="⏳ Расшифровываю голосовое...")
            text = await media.transcribe_voice(context.bot, msg.voice)
            kb = fmt.kb_collect(feature, st.context_items)
            if text:
                st.context_items.append(f"[Голосовое]\n{text}")
                kb = fmt.kb_collect(feature, st.context_items)
                await self._send(context, "✅ Голосовое добавлено.", keyboard=kb, edit=False)
            else:
                await self._send(context, "Не удалось расшифровать.", keyboard=kb, edit=False)
        elif msg.text and not msg.text.startswith("/"):
            st.context_items.append(f"[Текст]\n{msg.text.strip()}")
            kb = fmt.kb_collect(feature, st.context_items)
            await self._send(context, "✅ Текст добавлен.", keyboard=kb, edit=False)

    async def _answer_question(self, context, st: _SessionState, feature: "BillsFeature"):
        msg = context.message
        if not (msg.text and not msg.text.startswith("/")):
            return
        if not st.question_queue:
            return
        q = st.question_queue.pop(0)
        st.context_items.append(f"[Ответ на «{q['text']}»] {msg.text.strip()}")
        await self._send(context, f"✓ записал: {msg.text.strip()}", edit=False)
        await self._next_question(context, st, feature)

    async def _resolve_text(self, context, st: _SessionState, feature: "BillsFeature"):
        msg = context.message
        if not (msg.text and not msg.text.startswith("/")):
            return
        if not st.resolve_queue:
            return
        text = msg.text.strip()
        raw_name = st.resolve_queue[0][0]
        key = parse.norm_name_key(raw_name)
        person = None
        repo = feature.repository

        if text.startswith("@"):
            username = text.lstrip("@")
            person = repo.get_bill_person_by_username(username)
            if not person:
                real_user = next(
                    (u for u in repo.db.users if getattr(u, "username", None) == username),
                    None,
                )
                if real_user:
                    person, _ = repo.get_or_create_bill_person(
                        telegram_id=real_user.id,
                        display_name=real_user.name or username,
                        username=username,
                    )
            if not person:
                person, _ = repo.get_or_create_anonymous_person(f"@{username}")
        else:
            all_persons = repo.db.bill_persons
            users_map = {u.id: u for u in repo.db.users}
            person, _ = match_name(
                text,
                all_persons,
                users_map,
                caller_telegram_id=st.caller_tid,
                origin_chat_id=st.origin_chat_id,
                **feature._match_kwargs(st.caller_tid, st.origin_chat_id),
            )
            if not person:
                person, _ = repo.get_or_create_anonymous_person(text)

        st.resolve_queue.pop(0)
        st.resolved_map[key] = person.id
        await _learn_chat_nick(feature, st, raw_name, person)
        if st.resolve_queue:
            await self._next_disambiguation(context, st, feature)
        else:
            await self._show_preview(context, st, feature)

    async def _run_ai(self, context, st: _SessionState, feature: "BillsFeature") -> bool:
        if not st.context_items:
            await self._send(context, "Нет данных для анализа. Добавь фото, голосовое или текст.")
            return False

        repo = feature.repository
        caller = repo.get_bill_person_by_telegram_id(st.caller_tid)
        caller_name = caller.display_name if caller else None
        context_text = "\n\n".join(st.context_items)
        if caller_name:
            context_text = f"Я = {caller_name}\n\n" + context_text

        chat_persons = feature._chat_persons(st.caller_tid)
        directory_block = _build_directory_block(feature, st, chat_persons)
        prompt_input = f"{directory_block}\n\n---\n\n{context_text}"

        try:
            ai_response = await make_openrouter_query(
                user_id=f"bills_ocr_{st.caller_tid}",
                model=OpenRouterModel.GEMINI_25_FLASH,
                messages=[("user", prompt_input)],
                system_prompt=_bill_ocr_prompt(),
                max_tokens=4096,
                timeout_seconds=60.0,
            )
        except TimeoutError:
            logger.warning("AI OCR timed out for user %s", st.caller_tid)
            kb = fmt.kb_collect(feature, st.context_items)
            await self._send(context, "⏱ AI не ответил вовремя. Попробуй ещё раз.", keyboard=kb)
            return False
        except Exception as e:
            logger.exception("AI OCR failed: %s", e)
            kb = fmt.kb_collect(feature, st.context_items)
            await self._send(
                context,
                f"❗️ Ошибка AI: {e}\n\nДанные сохранены. Жми «✅ Готово» чтобы попробовать ещё раз "
                "или «❌ Отмена» чтобы отбросить счёт.",
                keyboard=kb,
            )
            return False

        ok = self._ingest_ai_rows(st, feature, ai_response)
        if not ok:
            kb = fmt.kb_collect(feature, st.context_items)
            await self._send(context, "AI не нашёл позиций. Попробуй добавить ещё данных.", keyboard=kb)
            return False
        return True

    def _ingest_ai_rows(self, st: _SessionState, feature: "BillsFeature", ai_response: str) -> bool:
        """Parse a [ОБЩЕЕ]-format AI response and update session state.

        Used by both initial OCR (`_run_ai`) and correction (`_apply_correction`).
        Returns True if rows were ingested OR questions were emitted.
        """
        repo = feature.repository
        chat_persons = feature._chat_persons(st.caller_tid)

        currency, rows, new_persons, questions = parse.parse_ai_response(ai_response)
        st.currency = currency
        st.new_person_names = new_persons
        st.question_queue = list(questions)

        if not rows and not questions:
            return False

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

        users_map = {u.id: u for u in repo.db.users}
        all_persons = repo.db.bill_persons
        resolve_queue = []
        resolved = dict(st.resolved_map)

        for key, raw in seen.items():
            if key in resolved:
                continue
            person, candidates = match_name(
                raw,
                all_persons,
                users_map,
                caller_telegram_id=st.caller_tid,
                origin_chat_id=st.origin_chat_id,
                **feature._match_kwargs(st.caller_tid, st.origin_chat_id),
            )
            if person and person.telegram_id:
                resolved[key] = person.id
            elif candidates:
                resolve_queue.append((raw, candidates))
            else:
                resolve_queue.append((raw, chat_persons))

        st.resolve_queue = resolve_queue
        st.resolved_map = resolved
        st.parsed_rows = rows
        return True

    async def _next_question(self, context, st: _SessionState, feature: "BillsFeature"):
        if not st.question_queue:
            await self._send(context, "⏳ Пересчитываю...")
            ok = await self._run_ai(context, st, feature)
            if not ok:
                return
            if st.question_queue:
                return await self._next_question(context, st, feature)
            if st.resolve_queue:
                return await self._next_disambiguation(context, st, feature)
            return await self._show_preview(context, st, feature)

        st.phase = "questions"
        q = st.question_queue[0]
        option_buttons = [
            feature.cb("bills:q_pick").button(opt, idx=i)
            for i, opt in enumerate(q["options"])
        ]
        rows = fmt.compact_grid(option_buttons, max_cols=3)
        await self._send(context, f"❓ {q['text']}", keyboard=Keyboard.grid(rows))

    async def _next_disambiguation(self, context, st: _SessionState, feature: "BillsFeature"):
        if not st.resolve_queue:
            return await self._show_preview(context, st, feature)
        st.phase = "resolve"
        raw_name, candidates = st.resolve_queue[0]
        chat_persons = feature._chat_persons(st.caller_tid)
        is_unknown = len(candidates) == len(chat_persons)
        if is_unknown:
            text = f"Не знаю кто такой «{raw_name}».\n_Выбери из знакомых, напиши @тег или имя_"
        else:
            names = ", ".join(p.display_name for p in candidates[:3])
            text = f"«{raw_name}» — это {names}?\n_Или напиши @тег / имя_"
        kb = fmt.kb_disambiguation(feature, candidates)
        await self._send(context, text, keyboard=kb)

    async def _handle_correction_input(
        self, context: ChatStepContext, st: _SessionState, feature: "BillsFeature"
    ):
        """In confirm phase, treat free-form text or voice as a correction request."""
        msg = context.message
        text: str | None = None
        if msg.voice:
            await context.bot.send_message(chat_id=msg.chat_id, text="⏳ Расшифровываю исправление...")
            text = await media.transcribe_voice(context.bot, msg.voice)
            if not text:
                await self._send(context, "Не удалось расшифровать. Попробуй ещё раз или текстом.")
                return
        elif msg.text and not msg.text.startswith("/"):
            text = msg.text.strip()
        if not text:
            return
        await self._apply_correction(context, st, feature, text)

    async def _apply_correction(
        self, context, st: _SessionState, feature: "BillsFeature", correction_text: str
    ):
        """Send the current bill state + correction to AI, ingest the revised table."""
        if not st.parsed_rows:
            await self._send(context, "Нет распознанного счёта для исправления.")
            return

        chat_persons = feature._chat_persons(st.caller_tid)
        directory = _build_directory_block(feature, st, chat_persons)
        general_block = parse.parsed_rows_to_general_block(st.parsed_rows)

        prompt_input = (
            f"[ТЕКУЩИЙ_СЧЁТ]\n"
            f"[META]\ncurrency: {st.currency}\n\n"
            f"{general_block}\n\n"
            f"---\n\n"
            f"{directory}\n\n"
            f"---\n\n"
            f"[ИСПРАВЛЕНИЕ]\n{correction_text}\n"
        )

        await self._send(context, "⏳ Применяю исправление...")
        try:
            ai_response = await make_openrouter_query(
                user_id=f"bills_correct_{st.caller_tid}",
                model=OpenRouterModel.GEMINI_25_FLASH,
                messages=[("user", prompt_input)],
                system_prompt=_bill_correct_prompt(),
                max_tokens=4096,
                timeout_seconds=60.0,
            )
        except TimeoutError:
            logger.warning("AI correction timed out for user %s", st.caller_tid)
            await self._send(
                context,
                "⏱ AI не ответил вовремя. Опиши исправление ещё раз или нажми «❌ Отмена».",
                keyboard=fmt.kb_confirm(feature),
            )
            return
        except Exception as e:
            logger.exception("AI correction failed: %s", e)
            await self._send(
                context,
                f"❗️ Ошибка AI: {e}\n\nИсправление не применено. Опиши его ещё раз или нажми «❌ Отмена».",
                keyboard=fmt.kb_confirm(feature),
            )
            return

        ok = self._ingest_ai_rows(st, feature, ai_response)
        if not ok:
            await self._send(
                context,
                "Не понял исправление — счёт остался без изменений. Попробуй переформулировать.",
                keyboard=fmt.kb_confirm(feature),
            )
            return

        if st.question_queue:
            await self._next_question(context, st, feature)
        elif st.resolve_queue:
            await self._next_disambiguation(context, st, feature)
        else:
            await self._show_preview(context, st, feature)

    async def _show_preview(self, context, st: _SessionState, feature: "BillsFeature"):
        repo = feature.repository
        for name in st.new_person_names:
            key = parse.norm_name_key(name)
            if key not in st.resolved_map or st.resolved_map[key] == UNKNOWN_PERSON_ID:
                person, _ = repo.get_or_create_anonymous_person(name)
                st.resolved_map[key] = person.id

        st.parsed_transactions = parse.rows_to_transactions(st.parsed_rows, st.resolved_map)
        st.phase = "confirm"
        text = fmt.format_preview(
            st.parsed_transactions,
            feature._persons(),
            st.currency,
            st.resolved_map,
        )
        await self._send(context, text, keyboard=fmt.kb_confirm(feature))

    # -- in-session callback handlers --

    async def _on_done(self, context: CallbackStepContext, st: _SessionState, feature: "BillsFeature") -> bool:
        if st.phase != "collect":
            try:
                await context.callback_query.answer("Нет активной сессии.", show_alert=True)
            except Exception:
                pass
            return False
        if not st.context_items:
            try:
                await context.callback_query.answer("Сначала добавь данные!", show_alert=True)
            except Exception:
                pass
            return False
        await self._send(context, "⏳ Анализирую данные...")
        ok = await self._run_ai(context, st, feature)
        if not ok:
            return False
        if st.question_queue:
            await self._next_question(context, st, feature)
        elif st.resolve_queue:
            await self._next_disambiguation(context, st, feature)
        else:
            await self._show_preview(context, st, feature)
        return False

    async def _on_cancel(self, context: CallbackStepContext):
        try:
            await context.callback_query.edit_message_text("❌ Отменено.")
        except Exception:
            pass

    async def _on_confirm(self, context: CallbackStepContext, st: _SessionState, feature: "BillsFeature"):
        if st.phase != "confirm":
            try:
                await context.callback_query.answer("Нет активной сессии.", show_alert=True)
            except Exception:
                pass
            return
        user = context.callback_query.from_user
        if st.is_suggestion:
            await feature._save_suggestion(context.bot, st, user, send_callback=self._send_callback(context))
        else:
            await feature._save_bill(context.bot, st, user, send_callback=self._send_callback(context))

    def _send_callback(self, context):
        async def _send(text: str, *, keyboard: Keyboard | None = None):
            return await self._send(context, text, keyboard=keyboard, edit=False)
        return _send

    async def _on_more(self, context, st: _SessionState, feature: "BillsFeature"):
        if st.phase not in ("confirm", "resolve"):
            try:
                await context.callback_query.answer("Нет активной сессии.", show_alert=True)
            except Exception:
                pass
            return
        st.phase = "collect"
        st.parsed_transactions = []
        st.resolve_queue = []
        st.new_person_names = []
        st.parsed_rows = []
        kb = fmt.kb_collect(feature, st.context_items)
        await self._send(
            context,
            "Давай ещё контекст. Пришли текст, фото или голосовое и нажми «Готово».",
            keyboard=kb,
        )

    async def _on_name_pick(self, context, st: _SessionState, feature: "BillsFeature", person_id: str):
        if not st.resolve_queue:
            return
        raw_name = st.resolve_queue.pop(0)[0]
        st.resolved_map[parse.norm_name_key(raw_name)] = person_id
        person = feature.repository.get_bill_person(person_id)
        if person:
            await _learn_chat_nick(feature, st, raw_name, person)
        if st.resolve_queue:
            await self._next_disambiguation(context, st, feature)
        else:
            await self._show_preview(context, st, feature)

    async def _on_name_new(self, context, st: _SessionState, feature: "BillsFeature"):
        if not st.resolve_queue:
            return
        raw_name = st.resolve_queue.pop(0)[0]
        person, _ = feature.repository.get_or_create_anonymous_person(raw_name)
        st.resolved_map[parse.norm_name_key(raw_name)] = person.id
        if st.resolve_queue:
            await self._next_disambiguation(context, st, feature)
        else:
            await self._show_preview(context, st, feature)

    async def _on_q_pick(self, context, st: _SessionState, feature: "BillsFeature", idx: int):
        if not st.question_queue:
            try:
                await context.callback_query.answer("Нет активного вопроса.", show_alert=True)
            except Exception:
                pass
            return
        q = st.question_queue[0]
        options = q["options"]
        if idx < 0 or idx >= len(options):
            return
        chosen = options[idx]

        if chosen.lower() == "другое":
            st.phase = "answering"
            await self._send(context, f"❓ {q['text']}\n→ Напиши ответ одним сообщением.")
            return

        st.question_queue.pop(0)
        st.context_items.append(f"[Ответ на «{q['text']}»] {chosen}")
        await self._next_question(context, st, feature)

    async def _on_change_list(self, context, st: _SessionState, feature: "BillsFeature"):
        if st.phase != "confirm":
            try:
                await context.callback_query.answer("Нет активной сессии.", show_alert=True)
            except Exception:
                pass
            return
        kb = fmt.kb_change_list(feature, st.resolved_map, feature._persons())
        try:
            await context.callback_query.edit_message_reply_markup(reply_markup=kb.to_markup())
        except Exception:
            pass

    async def _on_change_back(self, context, st: _SessionState, feature: "BillsFeature"):
        if st.phase != "confirm":
            try:
                await context.callback_query.answer("Нет активной сессии.", show_alert=True)
            except Exception:
                pass
            return
        try:
            await context.callback_query.edit_message_reply_markup(
                reply_markup=fmt.kb_confirm(feature).to_markup()
            )
        except Exception:
            pass

    async def _on_change_pick(self, context, st: _SessionState, feature: "BillsFeature", idx: int):
        if st.phase != "confirm":
            try:
                await context.callback_query.answer("Нет активной сессии.", show_alert=True)
            except Exception:
                pass
            return
        sorted_keys = sorted(st.resolved_map.keys())
        if idx < 0 or idx >= len(sorted_keys):
            return
        raw_key = sorted_keys[idx]
        persons = feature.repository.db.bill_persons
        kb = fmt.kb_change_pick(feature, idx, persons)
        try:
            await context.callback_query.edit_message_text(
                f"Кто такой «{raw_key.title()}»?",
                reply_markup=kb.to_markup(),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    async def _on_change_choose(self, context, st: _SessionState, feature: "BillsFeature", idx: int, person_id: str):
        if st.phase != "confirm":
            try:
                await context.callback_query.answer("Нет активной сессии.", show_alert=True)
            except Exception:
                pass
            return
        sorted_keys = sorted(st.resolved_map.keys())
        if idx < 0 or idx >= len(sorted_keys):
            return
        raw_key = sorted_keys[idx]
        st.resolved_map[raw_key] = person_id
        st.parsed_transactions = parse.rows_to_transactions(st.parsed_rows, st.resolved_map)
        by_id = feature._persons()
        text = fmt.format_preview(st.parsed_transactions, by_id, st.currency, st.resolved_map)
        try:
            await context.callback_query.edit_message_text(
                text,
                reply_markup=fmt.kb_confirm(feature).to_markup(),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        st.last_kb_msg = context.callback_query.message.message_id
        st.last_kb_chat = context.callback_query.message.chat_id

    async def _on_change_new(self, context, st: _SessionState, feature: "BillsFeature", idx: int):
        if st.phase != "confirm":
            try:
                await context.callback_query.answer("Нет активной сессии.", show_alert=True)
            except Exception:
                pass
            return
        sorted_keys = sorted(st.resolved_map.keys())
        if idx < 0 or idx >= len(sorted_keys):
            return
        raw_key = sorted_keys[idx]
        person, _ = feature.repository.get_or_create_anonymous_person(raw_key.title())
        st.resolved_map[raw_key] = person.id
        st.parsed_transactions = parse.rows_to_transactions(st.parsed_rows, st.resolved_map)
        by_id = feature._persons()
        text = fmt.format_preview(st.parsed_transactions, by_id, st.currency, st.resolved_map)
        try:
            await context.callback_query.edit_message_text(
                text,
                reply_markup=fmt.kb_confirm(feature).to_markup(),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        st.last_kb_msg = context.callback_query.message.message_id
        st.last_kb_chat = context.callback_query.message.chat_id


class _PayingStep(Step):
    """Single-purpose step that captures one '<amount> @user|name' message and creates a payment."""

    def __init__(self):
        pass

    async def chat(self, context: ChatStepContext) -> bool:
        st = context.session_context.get("paying")
        if st is None:
            return True
        feature = context.session_context["_feature"]
        bill_id = st["target_bill_id"]
        origin_chat_id = st["origin_chat_id"]

        if not st.get("announced"):
            st["announced"] = True
            bill = feature.repository.get_bill_v2(bill_id)
            name = bill.name if bill else f"#{bill_id}"
            await context.bot.send_message(
                chat_id=origin_chat_id,
                text=(
                    f"💸 Оплата по «{name}».\nПришли: «сумма @кому» или «сумма Имя».\n\n"
                    f"Для отмены: /stop"
                ),
            )
            return False

        msg = context.message
        if msg is None or not msg.text or msg.text.startswith("/"):
            return False
        m = re.match(r"([\d.,]+)\s+@?(\S.*)", msg.text.strip())
        if not m:
            await context.bot.send_message(
                chat_id=msg.chat_id,
                text="Формат: «сумма @username» или «сумма Имя».",
            )
            return False
        try:
            amount_minor = minor_from_float(float(m.group(1).replace(",", ".")))
        except ValueError:
            await context.bot.send_message(chat_id=msg.chat_id, text="Неверная сумма.")
            return False

        await feature._create_payment_for_user(
            context.bot,
            from_user=msg.from_user,
            amount_minor=amount_minor,
            target_name=m.group(2).strip(),
            chat_id=origin_chat_id,
            bill_id=bill_id,
            reply_chat_id=msg.chat_id,
        )
        return True

    async def callback(self, context: CallbackStepContext) -> bool:
        st = context.session_context.get("paying")
        if st is None:
            return True
        feature = context.session_context["_feature"]
        bill_id = st["target_bill_id"]
        origin_chat_id = st["origin_chat_id"]

        if not st.get("announced"):
            st["announced"] = True
            bill = feature.repository.get_bill_v2(bill_id)
            name = bill.name if bill else f"#{bill_id}"
            await context.bot.send_message(
                chat_id=origin_chat_id,
                text=(
                    f"💸 Оплата по «{name}».\nПришли: «сумма @кому» или «сумма Имя».\n\n"
                    f"Для отмены: /stop"
                ),
            )
        return False


class _GotStep(Step):
    """Captures one '<amount> @user|name' message — registers an auto-confirmed receipt."""

    def __init__(self):
        pass

    async def chat(self, context: ChatStepContext) -> bool:
        st = context.session_context.get("gotting")
        if st is None:
            return True
        feature = context.session_context["_feature"]
        bill_id = st["target_bill_id"]
        origin_chat_id = st["origin_chat_id"]

        if not st.get("announced"):
            st["announced"] = True
            bill = feature.repository.get_bill_v2(bill_id)
            name = bill.name if bill else f"#{bill_id}"
            await context.bot.send_message(
                chat_id=origin_chat_id,
                text=(
                    f"✅ Зачёт получения по «{name}».\nПришли: «сумма @откого» или «сумма Имя».\n\n"
                    f"Для отмены: /stop"
                ),
            )
            return False

        msg = context.message
        if msg is None or not msg.text or msg.text.startswith("/"):
            return False
        m = re.match(r"([\d.,]+)\s+@?(\S.*)", msg.text.strip())
        if not m:
            await context.bot.send_message(
                chat_id=msg.chat_id,
                text="Формат: «сумма @username» или «сумма Имя».",
            )
            return False
        try:
            amount_minor = minor_from_float(float(m.group(1).replace(",", ".")))
        except ValueError:
            await context.bot.send_message(chat_id=msg.chat_id, text="Неверная сумма.")
            return False

        await feature._creditor_initiated_payment(
            context.bot,
            from_user=msg.from_user,
            amount_minor=amount_minor,
            target_name=m.group(2).strip(),
            chat_id=origin_chat_id,
        )
        return True

    async def callback(self, context: CallbackStepContext) -> bool:
        st = context.session_context.get("gotting")
        if st is None:
            return True
        return False

    def stop(self):
        pass


def _split_cb(data: str) -> tuple[str, list[str]]:
    parts = data.split("|")
    return parts[0], parts[1:]


def _build_directory_block(
    feature: "BillsFeature",
    st: _SessionState,
    chat_persons: list,
) -> str:
    """Build the persons directory + chats block for the AI prompt.

    In a group chat: just chat_persons + their chat-scoped nicknames.
    In DM: chat_persons + a [ИЗВЕСТНЫЕ ЧАТЫ] section listing accessible chats
    with their members and nicks, so the AI can disambiguate cross-chat refs.
    """
    repo = feature.repository
    is_dm = st.origin_chat_id == st.caller_tid

    nicks_for_persons: dict[str, list[str]] = {}
    for n in repo.db.chat_nicknames:
        if is_dm or n.chat_id == st.origin_chat_id:
            nicks_for_persons.setdefault(n.person_id, []).append(n.nick)

    blocks: list[str] = [
        parse.build_persons_directory(
            chat_persons, chat_nicks_by_person=nicks_for_persons,
        )
    ]

    if is_dm:
        author = next(
            (u for u in repo.db.users if u.id == st.caller_tid), None,
        )
        chat_ids = set(getattr(author, "chat_ids", []) or []) if author else set()
        chats = [c for c in repo.db.chats if c.id in chat_ids]
        if chats:
            persons_by_id = {p.id: p for p in chat_persons}
            members_by_chat: dict[int, list] = {}
            for c in chats:
                members: list = []
                for p in chat_persons:
                    last_chats = set(p.chat_last_seen.keys())
                    if str(c.id) in last_chats:
                        members.append(p)
                members_by_chat[c.id] = members[:30]

            nicks_by_chat: dict[int, list[tuple[str, str]]] = {}
            for n in repo.db.chat_nicknames:
                if n.chat_id in chat_ids:
                    p = persons_by_id.get(n.person_id) or repo.get_bill_person(n.person_id)
                    if p:
                        nicks_by_chat.setdefault(n.chat_id, []).append(
                            (n.nick, p.display_name)
                        )

            chats_block = parse.build_chats_directory(chats, members_by_chat, nicks_by_chat)
            if chats_block:
                blocks.append(chats_block)
    return "\n\n".join(blocks)


async def _learn_chat_nick(
    feature: "BillsFeature",
    st: _SessionState,
    raw_name: str,
    person,
) -> None:
    """Implicit learning: when the user resolves a free-form name to a person in
    a real (group) chat, remember it as a chat-scoped nickname so next time the
    bot resolves it without asking. No-op for DM, conflicts, or trivial matches.
    """
    if person is None or not raw_name:
        return
    raw_name = raw_name.strip()
    if not raw_name or " " in raw_name or raw_name.startswith("@"):
        return
    chat_id = st.origin_chat_id
    if chat_id == st.caller_tid:
        return  # DM
    if raw_name.casefold() == person.display_name.casefold():
        return  # the bot would have matched display_name anyway
    repo = feature.repository
    existing = repo.find_chat_nickname(chat_id, raw_name)
    if existing is not None and existing.person_id != person.id:
        return  # don't override a conflicting nick that someone set explicitly
    if existing is not None:
        return  # already there
    repo.add_chat_nickname(
        chat_id=chat_id,
        person_id=person.id,
        nick=raw_name,
        created_by_telegram_id=st.caller_tid,
    )
    await repo.save()


class _ResolveByUsernameStep(Step):
    """Captures one «@username» message and binds the unbound BillPerson to it."""

    @staticmethod
    async def _announce_once(bot, st: dict, origin_chat_id: int, feature) -> None:
        if st.get("announced"):
            return
        st["announced"] = True
        person = feature.repository.get_bill_person(st["person_id"])
        who = person.display_name if person else "этому человеку"
        await bot.send_message(
            chat_id=origin_chat_id,
            text=(
                f"✏️ Пришли *@username* одним сообщением — привяжу к «{who}».\n"
                "Отмена: /stop"
            ),
            parse_mode="Markdown",
        )

    async def chat(self, context: ChatStepContext) -> bool:
        st = context.session_context.get("resolve_byname")
        if st is None:
            return True
        feature = context.session_context["_feature"]
        person_id: str = st["person_id"]
        origin_chat_id: int = st["origin_chat_id"]

        if not st.get("announced"):
            await self._announce_once(context.bot, st, origin_chat_id, feature)
            return False

        msg = context.message
        if msg is None or not msg.text or msg.text.startswith("/"):
            return False
        username = msg.text.strip().lstrip("@")
        if not username:
            await context.bot.send_message(
                chat_id=msg.chat_id, text="Нужен @username — попробуй ещё раз.",
            )
            return False

        repo = feature.repository
        person = repo.get_bill_person(person_id)
        if not person:
            await context.bot.send_message(chat_id=msg.chat_id, text="Уже привязано.")
            return True
        if person.telegram_id is not None:
            await context.bot.send_message(chat_id=msg.chat_id, text="Уже привязано.")
            return True

        existing = repo.get_bill_person_by_username(username)
        if existing is None:
            user = next(
                (u for u in repo.db.users if (u.username or "").lower() == username.lower()),
                None,
            )
            if user:
                existing, _ = repo.get_or_create_bill_person(
                    telegram_id=user.id,
                    display_name=user.username or str(user.id),
                    username=user.username,
                )

        if existing and existing.telegram_id is not None and existing.id != person.id:
            repo.merge_person(person.id, existing.id)
            target = existing
        elif existing and existing.telegram_id is not None and existing.id == person.id:
            target = person
        else:
            person.telegram_username = username
            target = person

        await repo.save()
        await context.bot.send_message(
            chat_id=msg.chat_id,
            text=f"✅ {target.display_name} привязан к @{username}.",
        )
        return True

    async def callback(self, context: CallbackStepContext) -> bool:
        st = context.session_context.get("resolve_byname")
        if st is None:
            return True
        feature = context.session_context["_feature"]
        await self._announce_once(
            context.bot, st, st["origin_chat_id"], feature,
        )
        return False

    def stop(self):
        pass
