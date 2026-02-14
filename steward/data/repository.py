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
            async with aiofiles.open(self.path, "r") as f:
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

        return data
