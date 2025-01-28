import json
import logging
import os
from abc import abstractmethod
from dataclasses import asdict
from enum import Enum

from dacite import Config, from_dict

from models.db import Database

logger = logging.getLogger("repository")


class Storage:
    @abstractmethod
    def read_dict(self) -> dict:
        pass

    @abstractmethod
    def write_dict(self, data: dict):
        pass


class JsonFileStorage(Storage):
    def __init__(self, path, cached=False):
        self.cached = cached
        self.cache = {}
        self.written = True  # True for first read

        self.path = path

    def read_dict(self):
        if self.cached and not self.written:
            return self.cache

        if not os.path.exists(self.path):
            open(self.path, "w").close()

        self.written = False
        data = open(self.path, "r", encoding="utf-8").read()
        if data.strip() == "":
            self.cache = {}
        else:
            self.cache = json.loads(data)
        return self.cache

    def write_dict(self, data):
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

        open(self.path, "w", encoding="utf-8").write(data)


class Repository:
    def __init__(self, storage: Storage):
        self._storage = storage

        data = storage.read_dict()
        migrated_data = self._migrate(data)
        self.db = from_dict(
            data_class=Database,
            data=migrated_data,
            config=Config(cast=[Enum]),
        )
        self.save()

    def save(self):
        self._storage.write_dict(asdict(self.db))

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
