from dataclasses import dataclass


@dataclass
class TodoItem:
    id: int
    chat_id: int
    text: str
    is_done: bool = False
