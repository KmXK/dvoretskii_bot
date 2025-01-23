import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class RulePattern:
    regex: str = ""
    ignore_case_flag: int = 1


@dataclass
class Response:
    from_chat_id: int
    message_id: int
    probability: int

    text: Optional[str] = None  # only for migration from version 1.*


@dataclass
class Rule:
    from_users: set[int]
    pattern: RulePattern
    responses: list[Response]
    tags: list[str]
    id: str = uuid.uuid4().hex
