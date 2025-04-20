from steward.data.models.rule import Rule
from steward.data.repository import Repository, Storage


class InMemoryStorage(Storage):
    def __init__(self, dict):
        self.dict = dict

    def read_dict(self):
        return self.dict

    def write_dict(self, data):
        self.dict = data


def test_initialization():
    repository = Repository(InMemoryStorage({}))

    repository.db.rules.append(
        Rule(
            from_users=[1, 2, 3], pattern="test", responses=["1", "2"], tags=["1", "2"]
        )
    )
    repository.save()

    data = repository._storage.read_dict()
    print(data)

    del data["version"]
    del data["admin_ids"]
    data["rules"] = [
        {k: v for k, v in rule.items() if k != "id"} for rule in data["rules"]
    ]

    assert repository._storage.read_dict() == {
        "rules": [
            {
                "from_users": [1, 2, 3],
                "pattern": "test",
                "responses": ["1", "2"],
                "tags": ["1", "2"],
            }
        ],
        "army": [],
        "chats": [],
    }


def test_migration_to_latest_version():
    repository = Repository(
        InMemoryStorage(
            {
                "AdminIds": [1, 2],
                "rules": [
                    {
                        "id": "d1835cabdaf845c496aa4b3f30f30bb7",
                        "from": 0,
                        "text": "test_text",
                        "response": "test_response",
                        "case_flag": 1,
                    }
                ],
                "version": 1,
                "army": [{"name": "Test", "date": "17.10.2025"}],
            }
        )
    )

    print(repository.db)

    assert repository.db.version == 2, "REWRITE TEST FOR NEW VERSION MIGRATION"
    assert repository.db.admin_ids == {***REMOVED***, ***REMOVED***}
    assert repository.db.rules[0].id == "d1835cabdaf845c496aa4b3f30f30bb7"
    assert repository.db.rules[0].from_users == {0}
    assert repository.db.rules[0].pattern.regex == "test_text"
    assert repository.db.rules[0].pattern.ignore_case_flag == 1
    assert repository.db.rules[0].tags == []
    assert repository.db.rules[0].responses[0].text == "test_response"
    assert repository.db.rules[0].responses[0].probability == 1
    assert repository.db.army[0].name == "Test"
    assert repository.db.army[0].date == "17.10.2025"
