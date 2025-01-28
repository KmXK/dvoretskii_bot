from dataclasses import dataclass, field

from .army import Army
from .chat import Chat
from .feature_request import FeatureRequest
from .rule import Rule


@dataclass
class Database:
    admin_ids: set[int] = field(default_factory=set)
    army: list[Army] = field(default_factory=list)
    chats: list[Chat] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    feature_requests: list[FeatureRequest] = field(default_factory=list)
    version: int = 3
