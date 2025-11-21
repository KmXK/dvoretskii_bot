from dataclasses import dataclass
from datetime import time


@dataclass
class ChannelSubscription:
    channel_id: int
    channel_username: str
    chat_id: int  # Куда отправлять сообщения
    times: list[time]  # Время отправки постов
    last_post_id: int  # ID последнего отправленного поста
    id: int = 0  # Будет установлен при создании
