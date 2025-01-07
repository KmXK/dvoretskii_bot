from abc import abstractmethod
from calendar import month
from dataclasses import asdict
import datetime
import json

from dacite import from_dict
import dateutil
import dateutil.relativedelta

from models.db import Database


class Storage:
    @abstractmethod
    def read_dict(self):
        pass

    @abstractmethod
    def write_dict(self, data: dict):
        pass


class JsonFileStorage(Storage):
    def __init__(self, path, cached = False):
        self.cached = cached
        self.cache = {}
        self.written = True # True for first read

        self.path = path

    def read_dict(self):
        if self.cached and not self.written:
            return self.cache

        self.written = False
        data = open(self.path, 'r', encoding='utf-8').read()
        if data.strip() == '':
            self.cache = {}
        else:
            self.cache = json.loads(data)
        return self.cache

    def write_dict(self, data):
        self.written = True
        open('db.json', 'w', encoding='utf-8').write(json.dumps(data, default=list, sort_keys=True, indent=4, ensure_ascii=False))


class Repository:
    def __init__(self, storage: Storage):
        self._storage = storage

        data = storage.read_dict()
        migrated_data = self._migrate(data)
        self.db = from_dict(data_class=Database, data=migrated_data)
        self.save()

    def save(self):
        self._storage.write_dict(asdict(self.db))

    def is_admin(self, user_id: str):
        return user_id in self.db.admin_ids

    def _migrate(self, data: dict):
        # default config
        if data.get('version') is None:
            data = {
                'admin_ids': [
                    ***REMOVED***,
                    ***REMOVED***
                ],
                'version': 2
            }

        if data['version'] < 2:
            data['admin_ids'] = data['AdminIds']
            del data['AdminIds']

            data['rules'] = [{
                    'id': rule['id'],
                    'from_users': [rule['from']],
                    'pattern': {
                        'regex': rule['text'],
                        'ignore_case_flag': rule['case_flag']
                    },
                    'responses': [
                        {
                            'from_chat_id': 0,
                            'message_id': 0,
                            'text': rule['response'],
                            'probability': 1
                        }
                    ],
                    'tags': []
                } for rule in data['rules']]

            data['version'] = 2

            for army in data['army']:
                end = datetime.datetime.strptime(army['date'], '%d.%m.%Y')
                start = datetime.datetime.strptime(army['date'], '%d.%m.%Y')
                army['end_date'] = end.timestamp()
                if end.month == 5:  # КОСТЫЛЬ
                    start.month
                    army['start_date'] = (end - dateutil.relativedelta.relativedelta(months=6)).timestamp()
                else:
                    army['start_date'] = (end - dateutil.relativedelta.relativedelta(years=1)).timestamp()

                del army['date']

        for rule in data.get('rules', []):
            rule['from_users'] = set(rule['from_users'])

        data['admin_ids'] = set(data['admin_ids'])

        return data


