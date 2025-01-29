from dataclasses import dataclass


@dataclass
class Chat:
    id: int
    name: str
    is_group_chat: bool
