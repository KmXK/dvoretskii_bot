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
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    on_callback,
    paginated,
    step,
    subcommand,
    wizard,
)
from steward.helpers.bills_money import minor_from_float, minor_to_display
from steward.helpers.bills_notifications import send_bill_notification
from steward.helpers.bills_person_match import match_name, update_chat_last_seen

from . import fmt, parse
from .session import (
    _BillCollectStep,
    _GotStep,
    _PayingStep,
    _ResolveByUsernameStep,
    _SessionState,
)

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

    def _match_kwargs(self, caller_tid: int, origin_chat_id: int) -> dict:
        """Build kwargs for match_name: chat_nicknames_index + scoped_chat_ids.

        scoped_chat_ids broadens the chat-nick lookup to all chats the caller is
        in — used in DM where the bare chat is the user's private chat.
        """
        author = next((u for u in self.repository.db.users if u.id == caller_tid), None)
        scoped = list(getattr(author, "chat_ids", []) or []) if author else []
        return {
            "chat_nicknames_index": self.repository.chat_nicknames_index(),
            "scoped_chat_ids": scoped,
        }

    def _is_dm(self, chat_id: int, caller_tid: int) -> bool:
        return chat_id == caller_tid

    async def _resolve_nick_target(
        self,
        ctx: FeatureContext,
        target: str,
    ):
        """Resolve the right-hand-side of `nick = target` to a BillPerson.

        - "@username" → existing BillPerson by username, or create from User, or anonymous
        - free text → match_name across the whole directory (chat-scoped first)
        Returns (person, created_flag) or (None, error_message).
        """
        target = target.strip()
        if not target:
            return None, "Пустое имя."

        if target.startswith("@"):
            username = target.lstrip("@")
            if not username:
                return None, "Пустой @."
            person = self.repository.get_bill_person_by_username(username)
            if not person:
                user = next(
                    (u for u in self.repository.db.users
                     if (u.username or "").lower() == username.lower()),
                    None,
                )
                if user:
                    display = (user.username or str(user.id))
                    person, _ = self.repository.get_or_create_bill_person(
                        telegram_id=user.id,
                        display_name=display,
                        username=user.username,
                    )
                else:
                    person, _ = self.repository.get_or_create_anonymous_person(f"@{username}")
            return person, None

        person, candidates = match_name(
            target,
            self.repository.db.bill_persons,
            self._users(),
            caller_telegram_id=ctx.user_id,
            origin_chat_id=ctx.chat_id,
            **self._match_kwargs(ctx.user_id, ctx.chat_id),
        )
        if person:
            return person, None
        if candidates:
            names = ", ".join(p.display_name for p in candidates[:5])
            return None, f"«{target}» неоднозначно: {names}. Уточни через @username."
        person, _ = self.repository.get_or_create_anonymous_person(target)
        return person, None

    async def _nick_set(self, ctx: FeatureContext, nick: str, target: str):
        if self._is_dm(ctx.chat_id, ctx.user_id):
            await ctx.reply(
                "Клички задаются внутри чата, не из лс.\n"
                "Зайди в нужный чат и выполни `/bills nick <ник> = <кому>`."
            )
            return
        if not nick:
            await ctx.reply("Пустой ник.")
            return
        if " " in nick:
            await ctx.reply("Ник без пробелов — одно слово.")
            return
        person, err = await self._resolve_nick_target(ctx, target)
        if err:
            await ctx.reply(err)
            return
        entry, status = self.repository.add_chat_nickname(
            chat_id=ctx.chat_id,
            person_id=person.id,
            nick=nick,
            created_by_telegram_id=ctx.user_id,
        )
        if status == "added":
            await self.repository.save()
            await ctx.reply(f"✅ В этом чате «{nick}» = {person.display_name}.")
        elif status == "exists":
            await ctx.reply(f"«{nick}» уже указывает на {person.display_name}.")
        elif status == "conflict":
            other = self.repository.get_bill_person(entry.person_id)
            await ctx.reply(
                f"«{nick}» в этом чате уже занят: {other.display_name if other else '?'}.\n"
                f"Удали через `/bills nick remove {nick}` или выбери другой ник."
            )
        else:
            await ctx.reply("Не получилось.")

    async def _nick_remove(self, ctx: FeatureContext, nick: str):
        if self._is_dm(ctx.chat_id, ctx.user_id):
            await ctx.reply("Клички удаляются внутри чата, не из лс.")
            return
        nick = nick.strip()
        if not nick:
            await ctx.reply("Что удалить?")
            return
        removed = self.repository.remove_chat_nickname(ctx.chat_id, nick)
        if removed:
            await self.repository.save()
            await ctx.reply(f"✅ «{nick}» удалена.")
        else:
            await ctx.reply(f"«{nick}» не найдена.")

    async def _show_nicks(self, ctx: FeatureContext):
        by_id = self._persons()
        if self._is_dm(ctx.chat_id, ctx.user_id):
            author = next(
                (u for u in self.repository.db.users if u.id == ctx.user_id), None,
            )
            chat_ids = list(getattr(author, "chat_ids", []) or [])
            chats_by_id = {c.id: c for c in self.repository.db.chats}
            grouped: dict[int, list] = {}
            for n in self.repository.db.chat_nicknames:
                if n.chat_id in chat_ids:
                    grouped.setdefault(n.chat_id, []).append(n)
            if not grouped:
                await ctx.reply("Кличек пока нет. Задавай в чатах: `/bills nick <ник> = @user`.")
                return
            lines = ["📛 *Клички по чатам:*"]
            for cid, nicks in grouped.items():
                chat = chats_by_id.get(cid)
                title = chat.name if chat else f"chat {cid}"
                lines.append(f"\n*{title}*")
                for n in sorted(nicks, key=lambda x: x.nick.casefold()):
                    p = by_id.get(n.person_id)
                    pname = p.display_name if p else "?"
                    lines.append(f"  • {n.nick} → {pname}")
            await ctx.reply("\n".join(lines))
            return

        nicks = self.repository.list_chat_nicknames(ctx.chat_id)
        if not nicks:
            await ctx.reply(
                "В этом чате кличек нет. Задай через `/bills nick <ник> = @user`,\n"
                "или ответом на сообщение — `/bills bind <ник>`."
            )
            return
        lines = ["📛 *Клички этого чата:*"]
        for n in sorted(nicks, key=lambda x: x.nick.casefold()):
            p = by_id.get(n.person_id)
            pname = p.display_name if p else "?"
            lines.append(f"  • {n.nick} → {pname}")
        await ctx.reply("\n".join(lines))

    async def _show_chat_aliases(self, ctx: FeatureContext):
        if self._is_dm(ctx.chat_id, ctx.user_id):
            author = next(
                (u for u in self.repository.db.users if u.id == ctx.user_id), None,
            )
            chat_ids = set(getattr(author, "chat_ids", []) or [])
            chats = [c for c in self.repository.db.chats if c.id in chat_ids]
            if not chats:
                await ctx.reply("Ты пока не в общих чатах с ботом.")
                return
            lines = ["💬 *Чаты, доступные тебе:*"]
            for c in chats:
                aliases_str = (
                    f"  · алиасы: {', '.join(c.aliases)}" if c.aliases else ""
                )
                lines.append(f"  • *{c.name}* (id `{c.id}`){aliases_str}")
            lines.append(
                "\nЧтобы добавить алиас — зайди в чат и выполни `/bills chat <alias>`."
            )
            await ctx.reply("\n".join(lines))
            return
        chat = self.repository.get_chat(ctx.chat_id)
        if not chat:
            await ctx.reply("Этот чат пока не учтён.")
            return
        aliases_str = ", ".join(chat.aliases) if chat.aliases else "(нет)"
        await ctx.reply(
            f"💬 *{chat.name}*\nАлиасы: {aliases_str}\n\n"
            f"Добавить: `/bills chat <alias>` · Удалить: `/bills chat remove <alias>`"
        )

    async def _bind_via_reply(self, ctx: FeatureContext, nick: str, *, self_bind: bool):
        if self._is_dm(ctx.chat_id, ctx.user_id):
            await ctx.reply("Эта команда работает только в групповых чатах.")
            return
        if not nick:
            await ctx.reply("Формат: `/bills bind <ник>` (ответом на сообщение).")
            return
        if " " in nick:
            await ctx.reply("Ник без пробелов — одно слово.")
            return

        target_user = None
        if self_bind:
            target_user = ctx.message.from_user if ctx.message else None
        else:
            reply = (ctx.message.reply_to_message if ctx.message else None)
            if reply is None:
                await ctx.reply(
                    "Это работает ответом на сообщение того, кого хочешь привязать.\n"
                    "Если речь о тебе самом — `/bills iam <ник>`."
                )
                return
            target_user = reply.from_user
        if target_user is None:
            await ctx.reply("Не вижу автора сообщения.")
            return

        person, _ = self.repository.get_or_create_bill_person(
            telegram_id=target_user.id,
            display_name=target_user.full_name or target_user.username or str(target_user.id),
            username=target_user.username,
        )
        entry, status = self.repository.add_chat_nickname(
            chat_id=ctx.chat_id,
            person_id=person.id,
            nick=nick,
            created_by_telegram_id=ctx.user_id,
        )
        if status == "conflict":
            other = self.repository.get_bill_person(entry.person_id)
            await ctx.reply(
                f"«{nick}» в этом чате уже занят: {other.display_name if other else '?'}.\n"
                f"Удали через `/bills nick remove {nick}` или выбери другой ник."
            )
            return
        await self.repository.save()
        if status == "exists":
            await ctx.reply(f"✅ «{nick}» уже = {person.display_name}.")
        else:
            await ctx.reply(
                f"✅ Запомнил: в этом чате «{nick}» = {person.display_name} "
                f"(@{target_user.username})."
                if target_user.username else
                f"✅ Запомнил: в этом чате «{nick}» = {person.display_name}."
            )

    def _unbound_persons_for_chat(self, chat_id: int) -> list:
        """BillPersons referenced in this chat's bills that have no telegram_id."""
        chat_bills = [b for b in self.repository.db.bills_v2 if b.origin_chat_id == chat_id]
        if not chat_bills:
            return []
        seen: set[str] = set()
        for b in chat_bills:
            seen.add(b.author_person_id)
            seen.update(b.participants)
        by_id = {p.id: p for p in self.repository.db.bill_persons}
        return [
            by_id[pid] for pid in seen
            if pid in by_id and by_id[pid].telegram_id is None
        ]

    def _unbound_for_resolve(self, caller_tid: int) -> list:
        """Unbound persons available in the resolve-binding flow.

        Admins always see the system-wide list; regular users see only their own
        bills. The count shown on the «🔗 Связать имена» button uses the same
        scope so it never mismatches the list opened by the tap.
        """
        all_mode = self.repository.is_admin(caller_tid)
        _, _, bills = self._person_bills(caller_tid, all_mode=all_mode)
        return self._unbound_persons_visible_to(caller_tid, bills)

    def _unbound_persons_visible_to(self, caller_tid: int, bills: list[BillV2]) -> list:
        """Caller-visible BillPersons without telegram_id, worth asking the user to bind.

        Filters out:
          - persons explicitly marked as not-on-TG (alias 'external')
          - persons appearing only in closed bills (settled history — don't bug the user)
        """
        in_open: set[str] = set()
        in_any: set[str] = set()
        for b in bills:
            ids = {b.author_person_id, *b.participants}
            in_any.update(ids)
            if not b.closed:
                in_open.update(ids)
        by_id = {p.id: p for p in self.repository.db.bill_persons}
        out = []
        for pid in in_any:
            p = by_id.get(pid)
            if p is None or p.telegram_id is not None:
                continue
            if "external" in (p.aliases or []):
                continue
            if pid not in in_open:
                continue
            out.append(p)
        return out

    def _telegram_candidates_for(
        self,
        person: "BillPerson",
        chat_id: int,
        caller_tid: int,
        limit: int = 8,
    ) -> list[tuple[int, str, float]]:
        """Rank chat-member Telegram users as binding candidates for `person`.

        For DM context, broadens to all caller chats. Returns
        (telegram_id, display_label, score) sorted desc.
        """
        from steward.helpers.bills_person_match import fuzzy_score_telegram_candidate

        users_map = self._users()
        bound_tids = {p.telegram_id for p in self.repository.db.bill_persons if p.telegram_id}

        if self._is_dm(chat_id, caller_tid):
            caller = users_map.get(caller_tid)
            scoped_chat_ids = set(getattr(caller, "chat_ids", []) or []) if caller else set()
            users = [u for u in self.repository.db.users if set(u.chat_ids or []) & scoped_chat_ids]
        else:
            users = [u for u in self.repository.db.users if chat_id in (u.chat_ids or [])]

        scored: list[tuple[int, str, float]] = []
        for u in users:
            if u.id in bound_tids:
                continue
            score = fuzzy_score_telegram_candidate(person.display_name, u, person)
            for alias in person.aliases or []:
                score = max(score, fuzzy_score_telegram_candidate(alias, u, person))
            label = (
                f"@{u.username}" if u.username else (u.stand_name or str(u.id))
            )
            scored.append((u.id, label, score))
        scored.sort(key=lambda x: -x[2])
        if any(s > 0 for _, _, s in scored):
            scored = [x for x in scored if x[2] > 0]
        return scored[:limit]

    def _find_unbound_person(self, person_short: str):
        """Look up a BillPerson whose id starts with `person_short` and has no telegram_id."""
        for p in self.repository.db.bill_persons:
            if p.id.startswith(person_short) and p.telegram_id is None:
                return p
        return None

    def _person_bills(self, tid: int, all_mode: bool = False):
        person = self.repository.get_bill_person_by_telegram_id(tid)
        is_admin = self.repository.is_admin(tid)
        if all_mode and is_admin:
            bills = list(self.repository.db.bills_v2)
        elif person:
            bills = self.repository.get_bills_v2_for_person(person.id)
            if not all_mode:
                bills = [b for b in bills if not b.closed]
        else:
            bills = []
        bills.sort(key=lambda b: (b.closed, -b.id))
        return person, is_admin, bills

    # -- Subcommands --

    @subcommand("", description="Список открытых счетов и долгов")
    async def cmd_list(self, ctx: FeatureContext):
        await self._show_overview(ctx, all_mode=False)

    @subcommand("all", description="Все счета (открытые + закрытые)")
    async def cmd_list_all(self, ctx: FeatureContext):
        await self._show_overview(ctx, all_mode=True)

    @subcommand("history", description="История моих переводов")
    async def cmd_history(self, ctx: FeatureContext):
        await self.paginate(ctx, "bills_history", metadata="all")

    @subcommand("help", description="Справка")
    async def cmd_help(self, ctx: FeatureContext):
        await ctx.reply(
            "📖 *Справка /bills*\n\n"
            "*Счета и платежи*\n"
            "/bills — список счетов и долги\n"
            "/bills add <название> — создать счёт\n"
            "/bills <id> — посмотреть счёт\n"
            "/bills pay <сумма> @user — я перевёл (pending)\n"
            "/bills got <сумма> @user — мне перевели (auto-confirm)\n"
            "/bills history — история моих переводов\n"
            "/bills all — все счета (включая закрытые)\n"
            "\n*Имена и клички*\n"
            "/bills nick <ник> = @user — кличка в этом чате\n"
            "/bills nick <ник> = Имя — кличка для уже известного человека\n"
            "/bills nick remove <ник> — удалить\n"
            "/bills nicks — список кличек\n"
            "/bills bind <ник> — *в ответ на сообщение* привязать автора\n"
            "/bills iam <ник> — кличка для меня самого в этом чате\n"
            "/bills alias <имя> = <псевдоним> — глобальный псевдоним\n"
            "\n*Чаты (для резолва из лс)*\n"
            "/bills chat <alias> — короткий алиас для текущего чата\n"
            "/bills chat — список чатов и алиасов\n"
            "\n*Прочее*\n"
            "/bills notify — настройки уведомлений"
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

    @subcommand("pay <amount:float> <target:rest>", description="Я перевёл @user — pending до его подтверждения")
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

    @subcommand("got <amount:float> <target:rest>", description="@user перевёл мне — auto-confirm")
    async def cmd_got(self, ctx: FeatureContext, amount: float, target: str):
        target = target.strip()
        if not target:
            await ctx.reply("Формат: /bills got 100 @username")
            return
        try:
            amount_minor = minor_from_float(amount)
        except ValueError:
            await ctx.reply("Неверная сумма.")
            return
        await self._creditor_initiated_payment(
            ctx.bot,
            from_user=ctx.message.from_user,
            amount_minor=amount_minor,
            target_name=target.lstrip("@"),
            chat_id=ctx.chat_id,
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
            **self._match_kwargs(ctx.user_id, ctx.chat_id),
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

    # -- Per-chat nicknames --

    @subcommand("nicks", description="Список кличек этого чата")
    async def cmd_nicks(self, ctx: FeatureContext):
        await self._show_nicks(ctx)

    @subcommand(
        "nick <text:rest>",
        description="Кличка для чата: ник = @user или ник = Имя",
    )
    async def cmd_nick(self, ctx: FeatureContext, text: str):
        text = text.strip()
        if not text:
            await ctx.reply(
                "Формат: `/bills nick <ник> = @user` или `/bills nick <ник> = Имя`\n"
                "Удалить: `/bills nick remove <ник>`"
            )
            return
        if text.lower().startswith("remove "):
            await self._nick_remove(ctx, text[len("remove "):].strip())
            return
        m = re.match(r"(.+?)\s*=\s*(.+)", text)
        if not m:
            await ctx.reply("Формат: `/bills nick <ник> = @user` или `<ник> = Имя`")
            return
        nick, target = m.group(1).strip(), m.group(2).strip()
        await self._nick_set(ctx, nick, target)

    @subcommand(
        "bind <nick:rest>",
        description="Ответом на сообщение: «/bills bind <ник>» — связать автора и сохранить кличку",
    )
    async def cmd_bind(self, ctx: FeatureContext, nick: str):
        await self._bind_via_reply(ctx, nick.strip(), self_bind=False)

    @subcommand(
        "iam <nick:rest>",
        description="«я в этом чате — Х»: ставит кличку себе и привязывается",
    )
    async def cmd_iam(self, ctx: FeatureContext, nick: str):
        await self._bind_via_reply(ctx, nick.strip(), self_bind=True)

    @subcommand(
        "chat <alias:rest>",
        description="Алиас текущего чата (использовать в лс: «из <alias>»)",
    )
    async def cmd_chat_alias(self, ctx: FeatureContext, alias: str):
        alias = alias.strip()
        if not alias:
            await self._show_chat_aliases(ctx)
            return
        if alias.lower().startswith("remove "):
            target = alias[len("remove "):].strip()
            removed = self.repository.remove_chat_alias(ctx.chat_id, target)
            if removed:
                await self.repository.save()
                await ctx.reply(f"✅ Алиас «{target}» удалён.")
            else:
                await ctx.reply(f"Алиас «{target}» не найден.")
            return
        if self._is_dm(ctx.chat_id, ctx.user_id):
            await ctx.reply(
                "Алиас чата задаётся внутри самого чата, не из лс.\n"
                "Зайди в нужный чат и выполни `/bills chat <alias>`."
            )
            return
        result = self.repository.add_chat_alias(ctx.chat_id, alias)
        if result == "added":
            await self.repository.save()
            await ctx.reply(f"✅ Чат теперь также откликается на «{alias}».")
        elif result == "exists":
            await ctx.reply(f"Алиас «{alias}» уже задан.")
        elif result == "conflict":
            owner = self.repository.find_chat_by_alias(alias)
            await ctx.reply(
                f"«{alias}» уже занят чатом «{owner.name if owner else '?'}»."
            )
        else:
            await ctx.reply("Не получилось.")

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
        await self._render_overview(ctx, all_mode=all_mode, edit=False)

    async def _render_overview(
        self,
        ctx: FeatureContext,
        *,
        all_mode: bool,
        edit: bool,
        page: int = 0,
    ):
        tid = ctx.user_id
        person, is_admin, bills = self._person_bills(tid, all_mode)
        logger.info(
            "/bills list: tid=%s person=%s is_admin=%s bills=%d edit=%s",
            tid, person.id if person else None, is_admin, len(bills), edit,
        )
        if not bills:
            empty_text = "У тебя пока нет счетов. Создай первый: /bills add <название>"
            await (ctx.edit(empty_text) if edit else ctx.reply(empty_text))
            return

        by_id = self._persons()
        text = fmt.format_overview(
            bills,
            person.id if person else None,
            by_id,
            self.repository.db.bill_payments_v2,
            all_mode=all_mode,
        )

        rows: list[list[Button]] = []

        has_owe, has_owed = self._person_balance_directions(
            bills, person.id if person else None
        )
        action_row: list[Button] = []
        if has_owe:
            action_row.append(self.cb("bills:pay_overview").button("💸 Оплатить"))
        if has_owed:
            action_row.append(self.cb("bills:got_overview").button("✅ Получил"))
        if action_row:
            rows.append(action_row)

        unbound = self._unbound_for_resolve(ctx.user_id)
        if unbound:
            rows.append([
                self.cb("bills:resolve_list").button(
                    f"🔗 Связать имена ({len(unbound)})",
                )
            ])

        rows.append([
            self.cb("bills:list_open").button("📋 Список счетов"),
            self.cb("bills:pairs").button("⚖️ Общие долги"),
        ])
        rows.append([
            self.cb("bills:hist_open").button("📜 История"),
            self.cb("bills:new").button("➕ Новый счёт"),
        ])
        keyboard = Keyboard.grid(rows)
        if edit:
            await ctx.edit(text, keyboard=keyboard)
        else:
            await ctx.reply(text, keyboard=keyboard)

    def _page_nav_factory(self, view: str):
        def make(p: int, label: str, *, noop: bool = False):
            if noop:
                return self.cb("bills:noop").button(label)
            return self.cb("bills:page").button(label, view=view, page=p)
        return make

    def _person_balance_directions(
        self, bills: list[BillV2], person_id: str | None
    ) -> tuple[bool, bool]:
        """Return (has_owe, has_owed): does `person_id` owe anyone, and does anyone owe them,
        across the given open bills (after applying payments)."""
        if not person_id:
            return False, False
        from steward.helpers.bills_money import (
            apply_payments, compute_bill_debts, net_debts,
        )
        payments = self.repository.db.bill_payments_v2
        has_owe = False
        has_owed = False
        for bill in bills:
            if bill.closed:
                continue
            raw = compute_bill_debts(bill.transactions, bill.currency)
            net = net_debts(raw)
            bp = [p for p in payments if bill.id in p.bill_ids]
            after = apply_payments(net, bp, clamp_zero=True)
            if not has_owe:
                if any(amt > 0 for amt in after.get(person_id, {}).values()):
                    has_owe = True
            if not has_owed:
                for debtor, creds in after.items():
                    if debtor != person_id and creds.get(person_id, 0) > 0:
                        has_owed = True
                        break
            if has_owe and has_owed:
                break
        return has_owe, has_owed

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

    @on_callback("bills:overview", schema="")
    async def on_overview(self, ctx: FeatureContext):
        await self._render_overview(ctx, all_mode=False, edit=True)

    @on_callback("bills:pay_overview", schema="")
    async def on_pay_overview(self, ctx: FeatureContext):
        tid = ctx.user_id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        if not person:
            await ctx.toast("Сначала засветись в любом счёте.", alert=True)
            return
        by_id = self._persons()
        text, kb = fmt.kb_pay_global(
            self, person.id, by_id,
            self.repository.db.bills_v2,
            self.repository.db.bill_payments_v2,
            source_bill_id=0,
            back_to_overview=True,
        )
        await ctx.edit(text, keyboard=kb, markdown=False)

    @on_callback("bills:got_overview", schema="")
    async def on_got_overview(self, ctx: FeatureContext):
        tid = ctx.user_id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        if not person:
            await ctx.toast("Сначала засветись в любом счёте.", alert=True)
            return
        by_id = self._persons()
        text, kb = fmt.kb_got_global(
            self, person.id, by_id,
            self.repository.db.bills_v2,
            self.repository.db.bill_payments_v2,
            source_bill_id=0,
            back_to_overview=True,
        )
        await ctx.edit(text, keyboard=kb, markdown=False)

    # -- Resolve unbound persons (binding) --

    @on_callback("bills:resolve_list", schema="")
    async def on_resolve_list(self, ctx: FeatureContext):
        unbound = self._unbound_for_resolve(ctx.user_id)
        if not unbound:
            await ctx.edit("✨ Все имена уже привязаны.")
            return
        await ctx.edit(
            f"🔗 *Связать имена*\n\nВыбери, кого хочешь привязать к Telegram-юзеру:",
            keyboard=fmt.kb_resolve_list(self, unbound),
        )

    @on_callback("bills:resolve", schema="<person_short:str>")
    async def on_resolve(self, ctx: FeatureContext, person_short: str):
        person = self._find_unbound_person(person_short)
        if not person:
            await ctx.toast("Уже привязано или не найдено.", alert=True)
            await self.on_resolve_list(ctx)
            return
        candidates = self._telegram_candidates_for(
            person, ctx.chat_id, ctx.user_id,
        )
        if not candidates:
            text = (
                f"🔗 «{person.display_name}»\n\n"
                "Среди участников чата подходящих не нашлось.\n"
                "Попробуй ввести @username или отметь как не-TG."
            )
        else:
            top = candidates[0][2]
            verb = "Похоже на" if top >= 600 else "Кандидаты"
            names = ", ".join(label for _, label, _ in candidates[:3])
            text = f"🔗 «{person.display_name}»\n\n{verb}: {names}"
        await ctx.edit(text, keyboard=fmt.kb_resolve_picker(self, person, candidates))

    @on_callback("bills:resolve_pick", schema="<person_short:str>|<user_tid:int>")
    async def on_resolve_pick(
        self, ctx: FeatureContext, person_short: str, user_tid: int
    ):
        person = self._find_unbound_person(person_short)
        if not person:
            await ctx.toast("Уже привязано или не найдено.", alert=True)
            return

        existing = self.repository.get_bill_person_by_telegram_id(user_tid)
        if existing and existing.id != person.id:
            self.repository.merge_person(person.id, existing.id)
            target = existing
        else:
            user = next(
                (u for u in self.repository.db.users if u.id == user_tid), None,
            )
            person.telegram_id = user_tid
            if user and user.username:
                person.telegram_username = user.username
            target = person

        await self.repository.save()
        await ctx.toast(f"✅ {target.display_name} привязан.")
        await self.on_resolve_list(ctx)

    @on_callback("bills:resolve_skip", schema="<person_short:str>")
    async def on_resolve_skip(self, ctx: FeatureContext, person_short: str):
        person = self._find_unbound_person(person_short)
        if not person:
            await ctx.toast("Уже привязано или не найдено.", alert=True)
            return
        if "external" not in (person.aliases or []):
            person.aliases = list(person.aliases or []) + ["external"]
            await self.repository.save()
        await ctx.toast(f"🚫 «{person.display_name}» скрыт.")
        await self.on_resolve_list(ctx)

    @on_callback("bills:resolve_back", schema="")
    async def on_resolve_back(self, ctx: FeatureContext):
        await self.on_resolve_list(ctx)

    @on_callback("bills:resolve_byname", schema="<person_short:str>")
    async def on_resolve_byname(self, ctx: FeatureContext, person_short: str):
        person = self._find_unbound_person(person_short)
        if not person:
            await ctx.toast("Уже привязано или не найдено.", alert=True)
            return
        await self.start_session(
            [_ResolveByUsernameStep()],
            ctx,
            resolve_byname={
                "person_id": person.id,
                "origin_chat_id": ctx.chat_id,
                "caller_tid": ctx.user_id,
            },
            _feature=self,
        )

    # -- History --

    @on_callback("bills:hist_open", schema="")
    async def on_hist_open(self, ctx: FeatureContext):
        await self.paginate(ctx, "bills_history", metadata="all")

    @paginated("bills_history", per_page=8)
    def bills_history_page(self, ctx: FeatureContext, metadata: str):
        filter_ = metadata or "all"
        tid = ctx.user_id
        person = self.repository.get_bill_person_by_telegram_id(tid)
        if not person:
            return [], (lambda _: "📜 Истории нет — ты ещё не участвовал в платежах."), None
        by_id = self._persons()
        bills_by_id = {b.id: b for b in self.repository.db.bills_v2}
        chat_only = None if self._is_dm(ctx.chat_id, tid) else ctx.chat_id
        items = fmt.select_history(
            self.repository.db.bill_payments_v2,
            person.id,
            bills_by_id,
            filter_=filter_,
            show_chat_only_for=chat_only,
        )

        title_filter = {"all": "все", "recv": "полученные", "sent": "отправленные"}.get(
            filter_, "все",
        )
        head = f"📜 *История переводов* ({title_filter}, {len(items)})"

        def render(chunk):
            return fmt.render_history_table(chunk, by_id, bills_by_id, my_person_id=person.id, head=head)

        filter_row = []
        for key, label in (("all", "Все"), ("recv", "⬇ Полученные"), ("sent", "⬆ Отправленные")):
            if key == filter_:
                filter_row.append(self.cb("bills:noop").button(f"• {label}"))
            else:
                filter_row.append(self.page_button("bills_history", label, metadata=key, page=0))
        extra = Keyboard.grid([filter_row, [self.cb("bills:overview").button("« Назад")]])
        return items, render, extra

    @on_callback("bills:list_open", schema="")
    async def on_list_open(self, ctx: FeatureContext):
        await self._on_list(ctx, closed=False, page=0)

    @on_callback("bills:list_closed", schema="")
    async def on_list_closed(self, ctx: FeatureContext):
        await self._on_list(ctx, closed=True, page=0)

    @on_callback("bills:pairs", schema="")
    async def on_pairs(self, ctx: FeatureContext):
        tid = ctx.user_id
        _, _, bills = self._person_bills(tid, all_mode=False)
        if not bills:
            await ctx.edit("Нет открытых счетов.")
            return
        text = fmt.format_pairs(
            bills, self._persons(), self.repository.db.bill_payments_v2,
            all_mode=False,
        )
        kb = Keyboard.row(self.cb("bills:overview").button("« Назад"))
        await ctx.edit(text, keyboard=kb)

    @on_callback("bills:page", schema="<view:str>|<page:int>")
    async def on_page(self, ctx: FeatureContext, view: str, page: int):
        if view == "lo":
            await self._on_list(ctx, closed=False, page=page)
        elif view == "lc":
            await self._on_list(ctx, closed=True, page=page)

    async def _on_list(self, ctx: FeatureContext, closed: bool, page: int = 0):
        tid = ctx.user_id
        person, is_admin, bills = self._person_bills(tid, all_mode=True)
        logger.info(
            "_on_list: tid=%s person=%s bills=%d closed=%s page=%d",
            tid, person.id if person else None, len(bills), closed, page,
        )
        filtered = [b for b in bills if b.closed == closed]
        if not filtered:
            await ctx.edit(
                "Нет закрытых счетов." if closed else "Нет открытых счетов.",
                keyboard=Keyboard.row(
                    self.cb("bills:list_open" if closed else "bills:list_closed").button(
                        "📂 Открытые" if closed else "📕 Закрытые"
                    ),
                    self.cb("bills:overview").button("« Назад"),
                ),
            )
            return
        bill_buttons = fmt.kb_bill_buttons(self, filtered)
        view = "lc" if closed else "lo"
        rows, _, _ = fmt.paginate_grid(
            bill_buttons,
            page=page,
            max_cols=2,
            max_rows=4,
            nav_factory=self._page_nav_factory(view),
        )
        toggle = self.cb(
            "bills:list_open" if closed else "bills:list_closed"
        ).button("📂 Открытые" if closed else "📕 Закрытые")
        rows.append([toggle, self.cb("bills:overview").button("« Назад")])
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
        bill = self.repository.get_bill_v2(bill_id) if bill_id else None
        if bill_id and not bill:
            await ctx.toast("Счёт не найден.", alert=True)
            return
        tid = ctx.user_id
        chat_id = ctx.chat_id
        await self.start_session(
            [_PayingStep()],
            ctx,
            paying={
                "target_bill_id": bill.id if bill else 0,
                "origin_chat_id": chat_id,
                "caller_tid": tid,
                "bill_name": bill.name if bill else "счетов",
            },
            _feature=self,
        )

    @on_callback("bills:got_start", schema="<bill_id:int>")
    async def on_got_start(self, ctx: FeatureContext, bill_id: int):
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
        text, kb = fmt.kb_got_global(self, pid, by_id, self.repository.db.bills_v2, payments, bill.id)
        await ctx.edit(text, keyboard=kb, markdown=False)

    @on_callback("bills:got_manual", schema="<bill_id:int>")
    async def on_got_manual(self, ctx: FeatureContext, bill_id: int):
        bill = self.repository.get_bill_v2(bill_id) if bill_id else None
        if bill_id and not bill:
            await ctx.toast("Счёт не найден.", alert=True)
            return
        tid = ctx.user_id
        chat_id = ctx.chat_id
        await self.start_session(
            [_GotStep()],
            ctx,
            gotting={
                "target_bill_id": bill.id if bill else 0,
                "origin_chat_id": chat_id,
                "caller_tid": tid,
                "bill_name": bill.name if bill else "счетов",
            },
            _feature=self,
        )

    @on_callback(
        "bills:qgot",
        schema="<bill_id:int>|<debtor_short:str>|<amount:int>",
    )
    async def on_quick_got(
        self, ctx: FeatureContext, bill_id: int, debtor_short: str, amount: int
    ):
        if bill_id != 0 and not self.repository.get_bill_v2(bill_id):
            await ctx.toast("Счёт не найден.", alert=True)
            return
        debtor = next(
            (p for p in self.repository.db.bill_persons if p.id.startswith(debtor_short)),
            None,
        )
        if not debtor:
            await ctx.toast("Должник не найден.", alert=True)
            return
        from_user = ctx.callback_query.from_user
        creditor, _ = self.repository.get_or_create_bill_person(
            telegram_id=from_user.id,
            display_name=from_user.full_name or str(from_user.id),
            username=from_user.username,
        )
        await self._apply_creditor_received(
            ctx.bot,
            creditor=creditor, debtor=debtor,
            amount_minor=amount, chat_id=ctx.chat_id,
        )
        try:
            await ctx.delete_or_clear_keyboard()
        except Exception:
            pass

    @on_callback(
        "bills:qpay",
        schema="<bill_id:int>|<creditor_short:str>|<amount:int>",
    )
    async def on_quick_pay(
        self, ctx: FeatureContext, bill_id: int, creditor_short: str, amount: int
    ):
        bill = self.repository.get_bill_v2(bill_id) if bill_id else None
        if bill_id and not bill:
            await ctx.toast("Счёт не найден.", alert=True)
            return
        currency = bill.currency if bill else "BYN"
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
        await self._register_payment(ctx.bot, debtor, creditor, amount, currency, chat_id)
        await ctx.edit(
            f"💸 Платёж {minor_to_display(amount, currency)} → {creditor.display_name} зарегистрирован.\n"
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

        if not confirm:
            payment.status = PaymentStatus.REJECTED
            await ctx.edit("❌ Получение не подтверждено.")
            await self.repository.save()
            return

        allocations, residual, auto_closed = self._confirm_and_split_payment(payment)
        debtor_p = self.repository.get_bill_person(payment.debtor)
        name = debtor_p.display_name if debtor_p else "?"
        msg = self._format_payment_outcome(
            header=(
                f"✅ Получение {minor_to_display(payment.amount_minor, payment.currency)} "
                f"от {name} подтверждено."
            ),
            allocations=allocations,
            residual=residual,
            auto_closed=auto_closed,
            currency=payment.currency,
        )
        await ctx.edit(msg)
        await self.repository.save()

    def _confirm_and_split_payment(
        self, payment: BillPaymentV2
    ) -> tuple[list[tuple[int, int]], int, list[BillV2]]:
        """Replace `payment` with N confirmed per-bill children based on greedy
        FIFO allocation across open bills with matching debt. Returns
        (allocations, residual, auto_closed_bills)."""
        from steward.helpers.bills_money import (
            apply_payments,
            compute_bill_debts,
            distribute_payment_amount,
            net_debts,
        )

        bills_with_debt: list[tuple[int, int]] = []
        for bill in sorted(self.repository.db.bills_v2, key=lambda b: b.created_at):
            if bill.closed:
                continue
            raw = compute_bill_debts(bill.transactions, bill.currency)
            net = net_debts(raw)
            other_payments = [
                p for p in self.repository.db.bill_payments_v2
                if p.id != payment.id and bill.id in p.bill_ids
            ]
            after = apply_payments(net, other_payments, clamp_zero=True)
            debt = after.get(payment.debtor, {}).get(payment.creditor, 0)
            if debt > 0:
                bills_with_debt.append((bill.id, debt))

        allocations, residual = distribute_payment_amount(
            bills_with_debt, payment.amount_minor
        )

        if payment in self.repository.db.bill_payments_v2:
            self.repository.db.bill_payments_v2.remove(payment)

        def _spawn(amount: int, bill_ids: list[int]) -> BillPaymentV2:
            return BillPaymentV2(
                id=str(uuid.uuid4()),
                debtor=payment.debtor,
                creditor=payment.creditor,
                amount_minor=amount,
                currency=payment.currency,
                status=PaymentStatus.CONFIRMED,
                created_at=datetime.now(),
                initiated_chat_id=payment.initiated_chat_id,
                confirmation_chat_id=payment.confirmation_chat_id,
                confirmation_message_id=payment.confirmation_message_id,
                bill_ids=bill_ids,
                is_refund=getattr(payment, "is_refund", False),
            )

        children = [_spawn(amt, [bid]) for bid, amt in allocations]
        if residual > 0:
            children.append(_spawn(residual, []))
        self.repository.db.bill_payments_v2.extend(children)

        auto_closed: list[BillV2] = []
        for bill_id, _ in allocations:
            bill = self.repository.get_bill_v2(bill_id)
            if not bill or bill.closed:
                continue
            raw = compute_bill_debts(bill.transactions, bill.currency)
            net = net_debts(raw)
            bp = [p for p in self.repository.db.bill_payments_v2 if bill_id in p.bill_ids]
            after = apply_payments(net, bp, clamp_zero=True)
            if not any(a > 0 for creds in after.values() for a in creds.values()):
                bill.closed = True
                bill.closed_at = datetime.now()
                auto_closed.append(bill)

        return allocations, residual, auto_closed

    def _format_payment_outcome(
        self,
        *,
        header: str,
        allocations: list[tuple[int, int]],
        residual: int,
        auto_closed: list[BillV2],
        currency: str,
    ) -> str:
        msg = header
        if len(allocations) > 1:
            parts = ", ".join(
                f"#{bid}: {minor_to_display(amt, currency)}"
                for bid, amt in allocations
            )
            msg += f"\n📊 Распределено: {parts}"
        if residual > 0:
            msg += (
                f"\n💰 Переплата {minor_to_display(residual, currency)} "
                "(нет открытого долга)"
            )
        for bill in auto_closed:
            msg += f"\n🔒 Счёт «{bill.name}» автоматически закрыт — все долги оплачены!"
        return msg

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

    async def _creditor_initiated_payment(
        self,
        bot,
        from_user,
        amount_minor: int,
        target_name: str,
        chat_id: int,
    ):
        creditor, _ = self.repository.get_or_create_bill_person(
            telegram_id=from_user.id,
            display_name=from_user.full_name or str(from_user.id),
            username=from_user.username,
        )
        debtor, candidates = match_name(
            target_name,
            self.repository.db.bill_persons,
            self._users(),
            caller_telegram_id=from_user.id,
            origin_chat_id=chat_id,
            **self._match_kwargs(from_user.id, chat_id),
        )
        if not debtor:
            text = (
                f"«{target_name}» неоднозначно: {', '.join(p.display_name for p in candidates[:5])}."
                if candidates
                else f"Не нашёл «{target_name}»."
            )
            await bot.send_message(chat_id=chat_id, text=text)
            return

        await self._apply_creditor_received(
            bot, creditor=creditor, debtor=debtor,
            amount_minor=amount_minor, chat_id=chat_id,
        )

    async def _apply_creditor_received(
        self,
        bot,
        *,
        creditor,
        debtor,
        amount_minor: int,
        chat_id: int,
    ):
        currency = "BYN"
        payment = BillPaymentV2(
            id=str(uuid.uuid4()),
            debtor=debtor.id,
            creditor=creditor.id,
            amount_minor=amount_minor,
            currency=currency,
            status=PaymentStatus.CONFIRMED,
            initiated_chat_id=chat_id,
            bill_ids=[],
        )
        self.repository.db.bill_payments_v2.append(payment)
        allocations, residual, auto_closed = self._confirm_and_split_payment(payment)

        amount_str = minor_to_display(amount_minor, currency)
        header = f"✅ Зачёт получения {amount_str} от {debtor.display_name}"
        msg = self._format_payment_outcome(
            header=header,
            allocations=allocations,
            residual=residual,
            auto_closed=auto_closed,
            currency=currency,
        )
        if not allocations and residual == amount_minor:
            msg += "\n_(нет открытых долгов от этого человека — записано как кредит)_"
        await bot.send_message(chat_id=chat_id, text=msg)

        await send_bill_notification(
            bot,
            self.repository,
            debtor,
            f"✅ {creditor.display_name} подтвердил, что ты перевёл *{amount_str}*",
            sender=creditor,
            parse_mode="Markdown",
            initiated_chat_id=chat_id,
        )
        await self.repository.save()
        logger.info(
            "Creditor-initiated payment: %s ← %s %s (allocs=%d, residual=%d)",
            creditor.display_name, debtor.display_name, amount_str,
            len(allocations), residual,
        )

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
            **self._match_kwargs(from_user.id, chat_id),
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
