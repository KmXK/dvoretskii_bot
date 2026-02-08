from dataclasses import dataclass


@dataclass
class AiMessage:
    timestamp: float
    message_id: int
    handler: str = ""
