from dataclasses import dataclass, field
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
    reaction_emoji: Optional[str] = None


@dataclass
class Rule:
    from_users: set[int]
    pattern: RulePattern
    responses: list[Response]
    tags: list[str]
    id: int = 0
    # Чаты, в которых правило срабатывает. Пустой набор => правило молчит везде.
    # Распространение правила = добавление чатов сюда (см. чат-пикер в rule.py).
    chats: set[int] = field(default_factory=set)
