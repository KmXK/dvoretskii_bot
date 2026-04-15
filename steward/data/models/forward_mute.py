from dataclasses import dataclass


@dataclass
class ForwardMute:
    chat_id: int
    user_id: int
