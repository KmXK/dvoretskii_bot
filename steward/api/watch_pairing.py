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


# ── QR-привязка (часы показывают QR, телефон сканирует) ───────────────────────
# Обратный поток к claim_code: инициатор — часы (камеры у них нет, поэтому QR
# показывают они, а сканирует телефон). Часы стартуют пэйринг и опрашивают
# статус; телефон, открыв вебаппу по deep-link из QR, подтверждает привязку.
#
#   1) часы → device_start() → (pair_id, secret); показывают QR с deep-link,
#      содержащим pair_id; начинают poll;
#   2) телефон сканирует QR → вебаппа (авторизована) → device_approve(pair_id,
#      user_id) → создаётся PairedDevice + токен, кладётся в пэндинг;
#   3) часы → device_poll(pair_id, secret) → получают токен один раз.
#
# secret защищает выдачу токена: знающий только pair_id (из QR) не утащит токен.

MAX_PENDING_PAIRS = 200


@dataclass
class _PendingDevicePair:
    secret_hash: str
    expires_at: float
    device_name: str = "Часы"
    user_id: int | None = None     # выставляется при approve
    raw_token: str | None = None   # выставляется при approve, отдаётся один раз


# pair_id → _PendingDevicePair (in-memory)
_pending_pairs: dict[str, _PendingDevicePair] = {}


def _prune_pairs(now: float | None = None) -> None:
    cur = now if now is not None else _now()
    for pid in [p for p, v in _pending_pairs.items() if v.expires_at <= cur]:
        _pending_pairs.pop(pid, None)
    if len(_pending_pairs) > MAX_PENDING_PAIRS:
        for pid in sorted(_pending_pairs, key=lambda x: _pending_pairs[x].expires_at)[
            : len(_pending_pairs) - MAX_PENDING_PAIRS
        ]:
            _pending_pairs.pop(pid, None)


def device_start(device_name: str = "Часы", *, now: float | None = None) -> tuple[str, str, int]:
    """Начать QR-привязку со стороны устройства. Возвращает (pair_id, secret, ttl)."""
    cur = now if now is not None else _now()
    _prune_pairs(cur)
    # token_urlsafe(9) — короткий id для компактного QR; алфавит [A-Za-z0-9_-]
    # совместим с Telegram startapp.
    pair_id = secrets.token_urlsafe(9)
    while pair_id in _pending_pairs:
        pair_id = secrets.token_urlsafe(9)
    secret = secrets.token_urlsafe(18)
    _pending_pairs[pair_id] = _PendingDevicePair(
        secret_hash=hash_token(secret),
        expires_at=cur + CODE_TTL_SECONDS,
        device_name=(device_name or "").strip()[:40] or "Часы",
    )
    return pair_id, secret, CODE_TTL_SECONDS


def device_approve(repository, pair_id: str, user_id: int, *, now: float | None = None) -> bool:
    """Подтвердить привязку (со стороны телефона/вебаппы). Создаёт PairedDevice."""
    cur = now if now is not None else _now()
    _prune_pairs(cur)
    pending = _pending_pairs.get(pair_id)
    if pending is None or pending.expires_at <= cur:
        return False
    if pending.user_id is not None:
        return True  # уже подтверждено — идемпотентно
    raw_token = secrets.token_urlsafe(32)
    from datetime import datetime, timezone

    next_id = max((d.id for d in repository.db.paired_devices), default=0) + 1
    device = PairedDevice(
        id=next_id,
        user_id=user_id,
        token_hash=hash_token(raw_token),
        name=pending.device_name,
        created_at=datetime.now(timezone.utc),
    )
    repository.db.paired_devices.append(device)
    pending.user_id = user_id
    pending.raw_token = raw_token
    return True


def device_poll(pair_id: str, secret: str, *, now: float | None = None) -> dict | None:
    """Опрос статуса со стороны устройства.

    None — pair_id неизвестен/истёк или secret неверный (→ 404/403 в роуте).
    {"status": "pending"} — ещё не подтверждено.
    {"status": "approved", "token", "user_id"} — подтверждено (токен отдаётся
    один раз, после чего пэндинг удаляется).
    """
    cur = now if now is not None else _now()
    _prune_pairs(cur)
    pending = _pending_pairs.get(pair_id)
    if pending is None or pending.expires_at <= cur:
        return None
    if not hmac.compare_digest(pending.secret_hash, hash_token(secret)):
        return None
    if pending.user_id is None:
        return {"status": "pending"}
    token = pending.raw_token
    _pending_pairs.pop(pair_id, None)  # одноразовая выдача
    return {"status": "approved", "token": token, "user_id": pending.user_id}
