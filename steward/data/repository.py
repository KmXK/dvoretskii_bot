import json
import logging
from abc import abstractmethod
from dataclasses import asdict
from enum import Enum
from inspect import isawaitable
from typing import Awaitable, Callable

import aiofiles
import aiofiles.os
from dacite import Config, from_dict

from steward.data.models.db import Database

logger = logging.getLogger(__name__)


class Storage:
    @abstractmethod
    async def read_dict(self) -> dict:
        pass

    @abstractmethod
    async def write_dict(self, data: dict):
        pass


class JsonFileStorage(Storage):
    def __init__(self, path, cached=False):
        self.cached = cached
        self.cache = {}
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
                default=list,
                sort_keys=True,
                indent=4,
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception(e)
            return

        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            await f.write(data)


class Repository:
    def __init__(self, storage: Storage):
        self._storage = storage
        self._save_callbacks: set[Callable[[], None | Awaitable]] = set()

        self.db = Database()

    async def migrate(self):
        data = await self._storage.read_dict()
        migrated_data = self._migrate(data)
        self.db = from_dict(
            data_class=Database,
            data=migrated_data,
            config=Config(cast=[Enum]),
        )
        await self.save()

    async def save(self):
        await self._storage.write_dict(asdict(self.db))
        for callback in self._save_callbacks:
            result = callback()
            if isawaitable(result):
                await result

    def subscribe_on_save(self, callback: Callable[[], Awaitable | None]):
        self._save_callbacks.add(callback)

    def unsubscribe_on_save(self, callback: Callable[[], Awaitable | None]):
        try:
            self._save_callbacks.remove(callback)
        except ValueError as e:
            logging.exception(e)
            pass

    def is_admin(self, user_id: int):
        return user_id in self.db.admin_ids

    def _migrate(self, data: dict):
        # default config
        if data.get("version") is None:
            data = {"admin_ids": [***REMOVED***, ***REMOVED***], "version": 2}

        # вроде как set() удалять нельзя, либа не справляется с конвертацией [] в set
        for rule in data.get("rules", []):
            rule["from_users"] = set(rule["from_users"])

        data["admin_ids"] = set(data["admin_ids"])

        id = 1
        for fq in data.get("feature_requests", []):
            fq["id"] = id
            id += 1

        return data
