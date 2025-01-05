import uuid

from Models.response import Response
from Models.rule_pattern import RulePattern

class Rule:
    def __init__(self, from_users: list[str], pattern: RulePattern, responses: list[Response], tags):
        self.id = uuid.uuid4().hex
        self.from_users = from_users
        self.pattern = pattern
        self.responses = responses
        self.tags = tags