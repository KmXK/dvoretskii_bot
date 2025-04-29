import datetime
import json
import logging
from abc import abstractmethod
from datetime import timedelta
from inspect import isawaitable
from typing import Any, Awaitable, Callable

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
            return o.timestamp()
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
            result = callback()
            if isawaitable(result):
                await result

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

        return data
