"""Привязка устройств (часов) по короткому коду + долгоживущие bearer-токены.

Поток:
  1) юзер в вебаппе (cookie-auth) зовёт start_pairing(user_id) → код + TTL,
     показывает его текстом и QR;
  2) часы зовут claim_code(code, name) → одноразово обменивают код на токен,
     сохраняется PairedDevice (хранится только sha256 токена);
  3) часы ходят в REST с `Authorization: Bearer <token>`; find_device_by_token
     резолвит юзера (см. steward.api.auth).

Пэндинг-коды живут в памяти (поток короткий, переживать рестарт не нужно);
сами токены устройств персистятся в repository.db.paired_devices.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from steward.data.models.paired_device import PairedDevice

# Код для часов: без неоднозначных символов (0/O, 1/I/L). Длина 8 → ~10^12
# вариантов, плюс одноразовость и TTL 5 минут.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_SECONDS = 300
MAX_PENDING_CODES = 200


@dataclass
class _PendingCode:
    user_id: int
    expires_at: float


# code → _PendingCode (in-memory)
_pending_codes: dict[str, _PendingCode] = {}


def _now() -> float:
    return time.time()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_code(raw: str) -> str:
    """Нормализуем введённый код: апперкейс, выкидываем пробелы/дефисы."""
    return "".join(ch for ch in (raw or "").upper() if ch in _CODE_ALPHABET)


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _prune_codes(now: float | None = None) -> None:
    cur = now if now is not None else _now()
    expired = [c for c, p in _pending_codes.items() if p.expires_at <= cur]
    for c in expired:
        _pending_codes.pop(c, None)
    # Защита от разрастания: если кодов слишком много — режем самые старые.
    if len(_pending_codes) > MAX_PENDING_CODES:
        for c in sorted(_pending_codes, key=lambda x: _pending_codes[x].expires_at)[
            : len(_pending_codes) - MAX_PENDING_CODES
        ]:
            _pending_codes.pop(c, None)


def start_pairing(user_id: int, *, now: float | None = None) -> tuple[str, int]:
    """Сгенерировать одноразовый код привязки. Возвращает (code, ttl_seconds).

    Старые pending-коды этого же юзера инвалидируются — активным остаётся
    только последний показанный.
    """
    cur = now if now is not None else _now()
    _prune_codes(cur)
    for c in [c for c, p in _pending_codes.items() if p.user_id == user_id]:
        _pending_codes.pop(c, None)
    code = _gen_code()
    while code in _pending_codes:
        code = _gen_code()
    _pending_codes[code] = _PendingCode(user_id=user_id, expires_at=cur + CODE_TTL_SECONDS)
    return code, CODE_TTL_SECONDS


def claim_code(
    repository,
    code: str,
    device_name: str,
    *,
    now: float | None = None,
) -> tuple[PairedDevice, str] | None:
    """Обменять код на устройство+токен. Код одноразовый.

    Возвращает (device, raw_token) при успехе либо None (код неверный/истёк).
    Сырой токен возвращается только здесь и больше нигде не хранится.
    """
    cur = now if now is not None else _now()
    _prune_codes(cur)
    normalized = normalize_code(code)
    pending = _pending_codes.get(normalized)
    if pending is None or pending.expires_at <= cur:
        return None
    # Одноразовость: сразу снимаем код.
    _pending_codes.pop(normalized, None)

    raw_token = secrets.token_urlsafe(32)
    name = (device_name or "").strip()[:40] or "Устройство"
    from datetime import datetime, timezone

    next_id = max((d.id for d in repository.db.paired_devices), default=0) + 1
    device = PairedDevice(
        id=next_id,
        user_id=pending.user_id,
        token_hash=hash_token(raw_token),
        name=name,
        created_at=datetime.now(timezone.utc),
    )
    repository.db.paired_devices.append(device)
    return device, raw_token


def find_device_by_token(repository, token: str) -> PairedDevice | None:
    """Найти устройство по сырому bearer-токену (сравнение по хэшу)."""
    if not token:
        return None
    candidate = hash_token(token)
    for device in repository.db.paired_devices:
        if hmac.compare_digest(device.token_hash, candidate):
            return device
    return None


def revoke_device(repository, user_id: int, device_id: int) -> bool:
    """Удалить устройство юзера. True если что-то удалили."""
    before = len(repository.db.paired_devices)
    repository.db.paired_devices = [
        d
        for d in repository.db.paired_devices
        if not (d.id == device_id and d.user_id == user_id)
    ]
    return len(repository.db.paired_devices) < before
