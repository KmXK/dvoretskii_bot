from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PairedDevice:
    """Долгоживущий токен устройства (напр. Galaxy Watch), привязанный к юзеру.

    Часы не умеют Telegram initData, поэтому привязываются по короткому коду
    из вебаппы и дальше ходят в REST с `Authorization: Bearer <token>`.

    Сам токен не храним — только его sha256-хэш (token_hash). Сравнение —
    через hmac.compare_digest по хэшу.
    """

    id: int
    user_id: int
    token_hash: str
    name: str = "Устройство"
    created_at: datetime = field(default_factory=_now)
    last_seen_at: datetime | None = None
