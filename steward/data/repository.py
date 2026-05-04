import asyncio
import datetime
import json
import logging
from abc import abstractmethod
from datetime import time, timedelta
from inspect import isawaitable
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import aiofiles
import aiofiles.os

logger = logging.getLogger(__name__)


class Storage:
    @abstractmethod
    async def read_dict(self) -> dict[str, Any]:
        pass

    @abstractmethod
    async def write_dict(self, data: dict[str, Any]):
        pass


class JsonEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, timedelta):
            return o.total_seconds()
        elif isinstance(o, datetime.datetime):
            return o.isoformat()
        elif isinstance(o, time):
            return o.isoformat()
        try:
            iterable = iter(o)
        except TypeError:
            pass
        else:
            return list(iterable)
        return super().default(o)


class JsonFileStorage(Storage):
    def __init__(self, path: str, cached=False):
        self.cached = cached
        self.cache: dict[str, Any] = {}
        self.written = True  # True for first read

        self.path = path

    async def read_dict(self):
        if self.cached and not self.written:
            return self.cache

        if not await aiofiles.os.path.exists(self.path):
            async with aiofiles.open(self.path, "w") as f:
                await f.close()

        self.written = False

        async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
            data = await f.read()

            if data.strip() == "":
                self.cache = {}
            else:
                self.cache = json.loads(data)

        return self.cache

    async def write_dict(self, data):
        self.written = True

        try:
            data = json.dumps(
                data,
                sort_keys=True,
                indent=4,
                ensure_ascii=False,
                cls=JsonEncoder,
            )
        except Exception as e:
            logger.exception(e)
            return

        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            await f.write(data)


class Repository:
    def __init__(self, storage: Storage):
        self._storage = storage
        self._save_lock = asyncio.Lock()
        self._save_callbacks: set[Callable[[], None | Awaitable[Any]]] = set()

        # Add abstraction on database to prevent cyclic dependencies and remove this kostil
        from steward.data.models.db import Database

        self.db = Database()

    async def migrate(self):
        data = await self._storage.read_dict()
        migrated_data = self._migrate(data)

        from steward.data.models.db import parse_from_dict

        self.db = parse_from_dict(migrated_data)
        await self.save()

    async def save(self):
        async with self._save_lock:
            from steward.data.models.db import serialize_to_dict

            await self._storage.write_dict(serialize_to_dict(self.db))
        for callback in self._save_callbacks:
            try:
                result = callback()
                if isawaitable(result):
                    await result
            except Exception as e:
                logging.exception(e)
                pass

    def subscribe_on_save(self, callback: Callable[[], Awaitable[Any] | None]):
        self._save_callbacks.add(callback)

    def unsubscribe_on_save(self, callback: Callable[[], Awaitable[Any] | None]):
        try:
            self._save_callbacks.remove(callback)
        except ValueError as e:
            logging.exception(e)
            pass

    def is_admin(self, user_id: int):
        return user_id in self.db.admin_ids

    def _migrate(self, data: dict[str, Any]):
        # TODO: Use config file
        # default config
        if data.get("version") is None:
            data = {"admin_ids": [], "version": 2}

        if data["version"] == 2:
            if "channel_subscriptions" in data:
                if "delayed_actions" not in data:
                    data["delayed_actions"] = []
                for x in data["channel_subscriptions"]:
                    for time in x["times"]:
                        data["delayed_actions"].append(
                            {
                                "__class_mark__": "delayed_action/channel_subscription",
                                "generator": {
                                    "__class_mark__": "generator/constant",
                                    "period": 86400.0,
                                    "start": datetime.datetime.combine(
                                        datetime.datetime.now(ZoneInfo("Europe/Minsk"))
                                        - datetime.timedelta(days=1),
                                        datetime.time.fromisoformat(time),
                                    ).timestamp(),
                                },
                                "subscription_id": x["id"],
                            }
                        )

            data["version"] = 3

        if data["version"] == 3:
            if "chats" in data and isinstance(data["chats"], list):
                seen_ids = set()
                unique_chats = []
                for chat in data["chats"]:
                    chat_id = chat.get("id")
                    if chat_id is not None and chat_id not in seen_ids:
                        seen_ids.add(chat_id)
                        unique_chats.append(chat)
                data["chats"] = unique_chats
            if "rules" in data and isinstance(data["rules"], list):
                seen_ids = set()
                unique_rules = []
                for rule in data["rules"]:
                    rule_id = rule.get("id")
                    if rule_id is not None and rule_id not in seen_ids:
                        seen_ids.add(rule_id)
                        unique_rules.append(rule)
                data["rules"] = unique_rules
            data["version"] = 4

        if data["version"] == 4:
            if "rules" in data and isinstance(data["rules"], list):
                max_id = 0
                for rule in data["rules"]:
                    rule_id = rule.get("id")

                    if isinstance(rule_id, str):
                        max_id += 1
                        rule["id"] = max_id
                    elif isinstance(rule_id, int):
                        if rule_id > max_id:
                            max_id = rule_id

                    if "responses" in rule and isinstance(rule["responses"], list):
                        responses = rule["responses"]
                        if len(responses) > 0:
                            old_sum = sum(
                                response.get("probability", 0)
                                for response in responses
                                if isinstance(response, dict)
                            )

                            if old_sum > 0:
                                new_probabilities = []
                                for response in responses:
                                    if isinstance(response, dict):
                                        old_prob = response.get("probability", 0)
                                        new_prob = round((old_prob * 1000) / old_sum)
                                        new_probabilities.append(new_prob)
                                    else:
                                        new_probabilities.append(0)

                                new_sum = sum(new_probabilities)
                                if new_sum > 1000:
                                    factor = 1000 / new_sum
                                    new_probabilities = [
                                        max(1, round(prob * factor))
                                        for prob in new_probabilities
                                    ]
                                    new_sum = sum(new_probabilities)
                                    if new_sum != 1000:
                                        diff = 1000 - new_sum
                                        for i in range(len(new_probabilities)):
                                            if new_probabilities[i] > 0:
                                                new_probabilities[i] += diff
                                                break

                                for i, response in enumerate(responses):
                                    if isinstance(response, dict) and i < len(
                                        new_probabilities
                                    ):
                                        response["probability"] = new_probabilities[i]
                            else:
                                if len(responses) > 0:
                                    prob_per_response = 1000 // len(responses)
                                    remainder = 1000 % len(responses)
                                    for i, response in enumerate(responses):
                                        if isinstance(response, dict):
                                            response["probability"] = (
                                                prob_per_response
                                                + (1 if i < remainder else 0)
                                            )
            data["version"] = 5

        if "bills" in data and "payments" not in data:
            payments = []
            for bill in data.get("bills", []):
                for p in bill.get("payments", []):
                    if isinstance(p, dict):
                        payments.append(
                            {
                                "person": p.get("person", ""),
                                "amount": p.get("amount", 0),
                                "creditor": p.get("creditor"),
                                "timestamp": p.get("timestamp"),
                            }
                        )
            data["payments"] = payments
            del data["bills"]

        if "bills" in data and isinstance(data["bills"], list):
            for i, bill in enumerate(data["bills"]):
                if isinstance(bill, dict) and "id" not in bill:
                    bill["id"] = i + 1

        if data.get("version") == 6:
            if "pasha_ai_messages" in data:
                ai_messages = {}
                for key, value in data["pasha_ai_messages"].items():
                    if isinstance(value, dict):
                        value["handler"] = "pasha"
                    ai_messages[key] = value
                data["ai_messages"] = ai_messages
                del data["pasha_ai_messages"]
            data["version"] = 7

        if data.get("version") == 7:
            for fr in data.get("feature_requests", []):
                if isinstance(fr, dict):
                    if "priority" not in fr or fr["priority"] not in range(1, 6):
                        fr["priority"] = 5
                    if "notes" not in fr:
                        fr["notes"] = []
            data["version"] = 8

        if data.get("version") == 8:
            for user in data.get("users", []):
                if isinstance(user, dict) and user.get("monkeys", 0) > 100000:
                    user["monkeys"] = 100
            data["version"] = 9

        if data.get("version") == 9:
            for user in data.get("users", []):
                if isinstance(user, dict) and user.get("id") == 685119817:
                    user["monkeys"] = 100
            data["version"] = 10

        if data.get("version") == 10:
            for user in data.get("users", []):
                if isinstance(user, dict) and user.get("id") == 685119817:
                    user["monkeys"] = 100
            data["version"] = 11

        if data.get("version") == 11:
            if "curse_words" not in data or not isinstance(data["curse_words"], list):
                data["curse_words"] = []
            if "curse_punishments" not in data or not isinstance(data["curse_punishments"], list):
                data["curse_punishments"] = []
            if "curse_participants" not in data or not isinstance(data["curse_participants"], list):
                data["curse_participants"] = []
            data["version"] = 12

        if data.get("version") == 12:
            if "user_facts" not in data or not isinstance(data["user_facts"], list):
                data["user_facts"] = []
            data["version"] = 13

        if data.get("version") == 13:
            try:
                import shutil as _shutil
                _shutil.copy(self._storage.path, self._storage.path + ".bak.v13")
            except Exception as _e:
                logger.warning("could not backup db.json before v14 migration: %s", _e)

            data.setdefault("bill_persons", [])
            data.setdefault("bills_v2", [])
            data.setdefault("bill_payments_v2", [])
            data.setdefault("bill_notification_prefs", [])
            data.setdefault("bill_diff_snapshots", [])
            data.setdefault("bill_item_suggestions", [])
            data.setdefault("bill_draft_edits", [])

            for p in data.get("bill_persons", []):
                p.setdefault("description", "")
                p.setdefault("chat_last_seen", {})

            for bill in data.get("bills_v2", []):
                bill.setdefault("currency", "BYN")
                bill.setdefault("origin_chat_id", None)
                bill.setdefault("updated_at", bill.get("created_at"))
                bill.setdefault("last_incomplete_reminder_at", None)
                for tx in bill.get("transactions", []):
                    tx.setdefault("unit_price_minor", 0)
                    tx.setdefault("quantity", 1)
                    tx.setdefault("assignments", [])
                    tx.setdefault("added_by_person_id", None)
                    tx.setdefault("source", "manual")

            for p in data.get("bill_payments_v2", []):
                if "amount_minor" not in p and "amount" in p:
                    p["amount_minor"] = int(round(float(p["amount"]) * 100))
                p.setdefault("currency", "BYN")

            data["version"] = 14

        if data.get("version") == 14:
            for p in data.get("bill_payments_v2", []):
                p.setdefault("is_refund", False)
            data["version"] = 15

        if data.get("version") == 15:
            data.setdefault("chat_nicknames", [])
            for c in data.get("chats", []):
                c.setdefault("aliases", [])
            data["version"] = 16

        # Idempotent fix-ups for DBs that ever touched the bills_v2 prototype.
        # Safe to run every startup.
        data.setdefault("bill_persons", [])
        data.setdefault("bills_v2", [])
        data.setdefault("bill_payments_v2", [])
        data.setdefault("bill_notification_prefs", [])
        data.setdefault("bill_diff_snapshots", [])
        data.setdefault("bill_item_suggestions", [])
        data.setdefault("bill_draft_edits", [])
        data.setdefault("chat_nicknames", [])
        for c in data.get("chats", []):
            c.setdefault("aliases", [])

        for p in data.get("bill_persons", []):
            p.setdefault("description", "")
            p.setdefault("chat_last_seen", {})
            p.setdefault("aliases", [])

        for bill in data.get("bills_v2", []):
            bill.setdefault("currency", "BYN")
            bill.setdefault("origin_chat_id", None)
            bill.setdefault("updated_at", bill.get("created_at"))
            bill.setdefault("last_incomplete_reminder_at", None)
            bill.setdefault("participants", [])
            bill.setdefault("transactions", [])
            for tx in bill.get("transactions", []):
                tx.setdefault("quantity", 1)
                tx.setdefault("added_by_person_id", None)
                tx.setdefault("source", "manual")
                tx.setdefault("incomplete", False)
                if "assignments" not in tx:
                    legacy_parts = tx.get("parts", [])
                    if legacy_parts:
                        tx["assignments"] = [
                            {"unit_count": 1, "debtors": list(part.get("debtors", []))}
                            for part in legacy_parts
                        ]
                        tx["quantity"] = len(legacy_parts)
                        if "unit_price_minor" not in tx:
                            total = sum(float(part.get("amount", 0)) for part in legacy_parts)
                            tx["unit_price_minor"] = int(round(total * 100))
                    else:
                        tx["assignments"] = []
                tx.setdefault("unit_price_minor", 0)

        for p in data.get("bill_payments_v2", []):
            if "amount_minor" not in p:
                if "amount" in p:
                    p["amount_minor"] = int(round(float(p["amount"]) * 100))
                else:
                    p["amount_minor"] = 0
            p.setdefault("currency", "BYN")
            p.setdefault("status", "pending")
            p.setdefault("bill_ids", [])
            p.setdefault("is_refund", False)

        return data

    # ── BillPerson ────────────────────────────────────────────────────────────

    def get_bill_person_by_telegram_id(self, telegram_id: int):
        for p in self.db.bill_persons:
            if p.telegram_id == telegram_id:
                return p
        return None

    def get_bill_person_by_username(self, username: str):
        username = username.lstrip("@").lower()
        for p in self.db.bill_persons:
            if p.telegram_username and p.telegram_username.lower() == username:
                return p
        return None

    def get_bill_person(self, person_id: str):
        for p in self.db.bill_persons:
            if p.id == person_id:
                return p
        return None

    def get_or_create_bill_person(
        self,
        telegram_id: int,
        display_name: str,
        username: str | None = None,
    ):
        import uuid
        from datetime import datetime
        from steward.data.models.bill_v2 import BillPerson

        existing = self.get_bill_person_by_telegram_id(telegram_id)
        if existing:
            changed = False
            if username and existing.telegram_username != username:
                existing.telegram_username = username
                existing.username_updated_at = datetime.now()
                changed = True
            if display_name and existing.display_name != display_name:
                existing.display_name = display_name
                changed = True
            return existing, changed
        person = BillPerson(
            id=str(uuid.uuid4()),
            display_name=display_name,
            telegram_id=telegram_id,
            telegram_username=username,
        )
        self.db.bill_persons.append(person)
        return person, True

    def get_or_create_anonymous_person(self, name: str):
        import uuid
        from steward.data.models.bill_v2 import BillPerson

        name_lower = name.lower()
        for p in self.db.bill_persons:
            if p.telegram_id is None and p.display_name.lower() == name_lower:
                return p, False
        person = BillPerson(id=str(uuid.uuid4()), display_name=name)
        self.db.bill_persons.append(person)
        return person, True

    def merge_person(self, src_id: str, dst_id: str) -> bool:
        """Reassign all bill/payment/nick references from src_id → dst_id and drop src.

        Used when the user binds an anonymous BillPerson to a Telegram user that
        already has a separate BillPerson record.
        """
        if src_id == dst_id:
            return False
        src = self.get_bill_person(src_id)
        dst = self.get_bill_person(dst_id)
        if not src or not dst:
            return False

        for bill in self.db.bills_v2:
            if bill.author_person_id == src_id:
                bill.author_person_id = dst_id
            if src_id in bill.participants:
                bill.participants = [
                    dst_id if pid == src_id else pid for pid in bill.participants
                ]
                seen: set[str] = set()
                bill.participants = [
                    p for p in bill.participants if not (p in seen or seen.add(p))
                ]
            for tx in bill.transactions:
                if tx.creditor == src_id:
                    tx.creditor = dst_id
                for asg in tx.assignments:
                    asg.debtors = [dst_id if d == src_id else d for d in asg.debtors]

        for pay in self.db.bill_payments_v2:
            if pay.debtor == src_id:
                pay.debtor = dst_id
            if pay.creditor == src_id:
                pay.creditor = dst_id

        for sug in self.db.bill_item_suggestions:
            if sug.proposed_by_person_id == src_id:
                sug.proposed_by_person_id = dst_id
            if sug.decided_by_person_id == src_id:
                sug.decided_by_person_id = dst_id
            for tx in sug.proposed_tx:
                if tx.creditor == src_id:
                    tx.creditor = dst_id
                for asg in tx.assignments:
                    asg.debtors = [dst_id if d == src_id else d for d in asg.debtors]

        for n in self.db.chat_nicknames:
            if n.person_id == src_id:
                n.person_id = dst_id

        for src_alias in src.aliases or []:
            if src_alias not in dst.aliases:
                dst.aliases.append(src_alias)
        for cid, last in (src.chat_last_seen or {}).items():
            prev = dst.chat_last_seen.get(cid)
            if prev is None or prev < last:
                dst.chat_last_seen[cid] = last

        self.db.bill_persons = [p for p in self.db.bill_persons if p.id != src_id]
        return True

    def merge_duplicate_anonymous_persons(self) -> list[str]:
        """After migration: merge anon BillPersons whose display_name matches a real person.
        Returns list of merged anon IDs (for logging)."""
        from steward.data.models.bill_v2 import BillPerson

        users_by_id = {u.id: u for u in self.db.users}
        anon_persons = [p for p in self.db.bill_persons if p.telegram_id is None]
        real_persons = [p for p in self.db.bill_persons if p.telegram_id is not None]
        merged_ids: list[str] = []

        for anon in anon_persons:
            anon_lower = anon.display_name.lower()
            match = None
            for real in real_persons:
                candidates = [real.display_name.lower()]
                candidates.extend(a.lower() for a in real.aliases)
                if real.telegram_username:
                    candidates.append(real.telegram_username.lower())
                user = users_by_id.get(real.telegram_id)
                if user:
                    if user.stand_name:
                        candidates.append(user.stand_name.lower())
                    candidates.extend(a.lower() for a in user.stand_aliases)
                if anon_lower in candidates:
                    match = real
                    break
            if not match:
                continue
            # Reassign all references
            for bill in self.db.bills_v2:
                if bill.author_person_id == anon.id:
                    bill.author_person_id = match.id
                if anon.id in bill.participants:
                    bill.participants = [
                        match.id if pid == anon.id else pid for pid in bill.participants
                    ]
                for tx in bill.transactions:
                    if tx.creditor == anon.id:
                        tx.creditor = match.id
                    for asg in tx.assignments:
                        asg.debtors = [match.id if d == anon.id else d for d in asg.debtors]
            for pay in self.db.bill_payments_v2:
                if pay.debtor == anon.id:
                    pay.debtor = match.id
                if pay.creditor == anon.id:
                    pay.creditor = match.id
            merged_ids.append(anon.id)

        self.db.bill_persons = [
            p for p in self.db.bill_persons if p.id not in merged_ids
        ]
        return merged_ids

    # ── BillV2 ────────────────────────────────────────────────────────────────

    def get_next_bill_v2_id(self) -> int:
        if not self.db.bills_v2:
            return 1
        return max(b.id for b in self.db.bills_v2) + 1

    def get_bill_v2(self, bill_id: int):
        for b in self.db.bills_v2:
            if b.id == bill_id:
                return b
        return None

    def get_bills_v2_for_person(self, person_id: str):
        return [
            b for b in self.db.bills_v2
            if person_id in b.participants or person_id == b.author_person_id
        ]

    def get_bills_v2_for_telegram_id(self, telegram_id: int):
        person = self.get_bill_person_by_telegram_id(telegram_id)
        if not person:
            return []
        return self.get_bills_v2_for_person(person.id)

    # ── BillPaymentV2 ─────────────────────────────────────────────────────────

    def get_bill_payment_v2(self, payment_id: str):
        for p in self.db.bill_payments_v2:
            if p.id == payment_id:
                return p
        return None

    def get_pending_bill_payments(self):
        from steward.data.models.bill_v2 import PaymentStatus
        return [p for p in self.db.bill_payments_v2 if p.status == PaymentStatus.PENDING]

    # ── BillNotificationPrefs ─────────────────────────────────────────────────

    def get_bill_notification_prefs(self, telegram_id: int):
        from steward.data.models.bill_v2 import BillNotificationPrefs

        for prefs in self.db.bill_notification_prefs:
            if prefs.telegram_id == telegram_id:
                return prefs
        prefs = BillNotificationPrefs(telegram_id=telegram_id)
        self.db.bill_notification_prefs.append(prefs)
        return prefs

    # ── BillDiffSnapshot ──────────────────────────────────────────────────────

    def get_bill_diff_snapshot(self, token: str):
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(hours=24)
        for s in self.db.bill_diff_snapshots:
            if s.token == token and s.created_at > cutoff:
                return s
        return None

    def cleanup_expired_diff_snapshots(self):
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(hours=24)
        self.db.bill_diff_snapshots = [
            s for s in self.db.bill_diff_snapshots if s.created_at > cutoff
        ]

    # ── BillItemSuggestion ────────────────────────────────────────────────────

    def get_bill_suggestion(self, suggestion_id: str):
        for s in self.db.bill_item_suggestions:
            if s.id == suggestion_id:
                return s
        return None

    def get_pending_suggestions_for_bill(self, bill_id: int):
        from steward.data.models.bill_v2 import SuggestionStatus
        return [
            s for s in self.db.bill_item_suggestions
            if s.bill_id == bill_id and s.status == SuggestionStatus.PENDING
        ]

    # ── BillDraftEdit ─────────────────────────────────────────────────────────

    def get_bill_draft_edit(self, draft_id: str):
        for d in self.db.bill_draft_edits:
            if d.id == draft_id:
                return d
        return None

    def cleanup_expired_drafts(self):
        from datetime import datetime

        now = datetime.now()
        self.db.bill_draft_edits = [
            d for d in self.db.bill_draft_edits
            if not d.merged and d.expires_at > now
        ]

    # ── ChatNickname ──────────────────────────────────────────────────────────

    @staticmethod
    def _norm_nick(s: str) -> str:
        return (s or "").strip().casefold()

    def list_chat_nicknames(self, chat_id: int):
        return [n for n in self.db.chat_nicknames if n.chat_id == chat_id]

    def find_chat_nickname(self, chat_id: int, nick: str):
        key = self._norm_nick(nick)
        if not key:
            return None
        for n in self.db.chat_nicknames:
            if n.chat_id == chat_id and self._norm_nick(n.nick) == key:
                return n
        return None

    def find_person_id_by_nick(self, chat_id: int, nick: str) -> str | None:
        n = self.find_chat_nickname(chat_id, nick)
        return n.person_id if n else None

    def add_chat_nickname(
        self,
        chat_id: int,
        person_id: str,
        nick: str,
        created_by_telegram_id: int | None = None,
    ):
        from steward.data.models.bill_v2 import ChatNickname

        nick = (nick or "").strip()
        if not nick:
            return None, "empty"
        existing = self.find_chat_nickname(chat_id, nick)
        if existing is not None:
            if existing.person_id == person_id:
                return existing, "exists"
            return existing, "conflict"
        entry = ChatNickname(
            chat_id=chat_id,
            person_id=person_id,
            nick=nick,
            created_by_telegram_id=created_by_telegram_id,
        )
        self.db.chat_nicknames.append(entry)
        return entry, "added"

    def remove_chat_nickname(self, chat_id: int, nick: str) -> bool:
        key = self._norm_nick(nick)
        before = len(self.db.chat_nicknames)
        self.db.chat_nicknames = [
            n for n in self.db.chat_nicknames
            if not (n.chat_id == chat_id and self._norm_nick(n.nick) == key)
        ]
        return len(self.db.chat_nicknames) < before

    def chat_nicknames_for_person(self, person_id: str):
        return [n for n in self.db.chat_nicknames if n.person_id == person_id]

    def chat_nicknames_index(self) -> dict[int, dict[str, str]]:
        """{chat_id: {nick_lower: person_id}} — built per-call; cheap (one O(N) pass)."""
        idx: dict[int, dict[str, str]] = {}
        for n in self.db.chat_nicknames:
            idx.setdefault(n.chat_id, {})[self._norm_nick(n.nick)] = n.person_id
        return idx

    # ── Chat ──────────────────────────────────────────────────────────────────

    def get_chat(self, chat_id: int):
        for c in self.db.chats:
            if c.id == chat_id:
                return c
        return None

    def find_chat_by_alias(self, alias: str):
        """Match a chat by user-defined alias (exact, case-insensitive) or by title."""
        key = self._norm_nick(alias)
        if not key:
            return None
        for c in self.db.chats:
            if self._norm_nick(c.name) == key:
                return c
            for a in (c.aliases or []):
                if self._norm_nick(a) == key:
                    return c
        return None

    def add_chat_alias(self, chat_id: int, alias: str) -> str:
        chat = self.get_chat(chat_id)
        if chat is None:
            return "no_chat"
        alias = (alias or "").strip()
        if not alias:
            return "empty"
        owner = self.find_chat_by_alias(alias)
        if owner is not None and owner.id != chat_id:
            return "conflict"
        existing = chat.aliases or []
        if any(self._norm_nick(a) == self._norm_nick(alias) for a in existing):
            return "exists"
        chat.aliases = existing + [alias]
        return "added"

    def remove_chat_alias(self, chat_id: int, alias: str) -> bool:
        chat = self.get_chat(chat_id)
        if chat is None:
            return False
        key = self._norm_nick(alias)
        before = len(chat.aliases or [])
        chat.aliases = [a for a in (chat.aliases or []) if self._norm_nick(a) != key]
        return len(chat.aliases) < before
