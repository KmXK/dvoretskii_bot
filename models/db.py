from dataclasses import dataclass, field

from models.army import Army
from models.chat import Chat
from models.rule import Rule


@dataclass
class Database:
    admin_ids: set[int] = field(default_factory=set)
    army: list[Army] = field(default_factory=list)
    chats: list[Chat] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    version: int = None
