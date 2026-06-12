from steward.data.repository import Repository, Storage


class SeededStorage(Storage):
    def __init__(self, data):
        self.data = data

    async def read_dict(self):
        return self.data

    async def write_dict(self, data):
        self.data = data


async def test_migration_v41_names_private_chats():
    repository = Repository(
        SeededStorage(
            {
                "version": 41,
                "admin_ids": [],
                "chats": [
                    {"id": 111, "name": "Unknown", "aliases": []},
                    {"id": 222, "name": "@None", "aliases": []},
                    {"id": 333, "name": "Unknown", "aliases": []},
                    {"id": -100500, "name": "Моя группа", "aliases": []},
                ],
                "users": [
                    {"id": 111, "username": "vasya", "first_name": "Вася", "chat_ids": [111]},
                    {"id": 222, "username": "petya", "chat_ids": [222]},
                ],
            }
        )
    )
    await repository.migrate()

    chats = {c.id: c.name for c in repository.db.chats}
    assert chats[111] == "ЛС: Вася"
    assert chats[222] == "ЛС: @petya"
    assert chats[333] == "ЛС: 333"
    assert chats[-100500] == "Моя группа"
    assert repository.db.version == 42
