from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChatTunnel:
    """Двунаправленный туннель между двумя чатами.

    Сообщения можно слать с любой из сторон командой `/tunnel <id> текст`,
    они пересылаются в другую сторону. Реплай на пришедшее сообщение
    улетает обратно.
    """

    id: int
    chat_a: int
    chat_b: int
    chat_a_name: str
    chat_b_name: str
    created_by: int
    created_at: datetime = field(default_factory=_now)

    def other_side(self, chat_id: int) -> int | None:
        if chat_id == self.chat_a:
            return self.chat_b
        if chat_id == self.chat_b:
            return self.chat_a
        return None

    def involves(self, chat_id: int) -> bool:
        return chat_id in (self.chat_a, self.chat_b)

    def name_of(self, chat_id: int) -> str:
        if chat_id == self.chat_a:
            return self.chat_a_name
        if chat_id == self.chat_b:
            return self.chat_b_name
        return str(chat_id)


@dataclass
class TunnelMessage:
    """Связь между исходным сообщением и его копией в другом чате.

    Нужна, чтобы реплай на пересланное сообщение можно было доставить
    обратно автору исходного.
    """

    tunnel_id: int
    src_chat: int
    src_msg_id: int
    dst_chat: int
    dst_msg_id: int
    sender_id: int
    created_at: datetime = field(default_factory=_now)
