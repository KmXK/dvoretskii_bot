"""Одноразовый init-контейнер: генерирует RSA-ключ для подписи Grafana JWT.

Пишет в /jwt (named volume):
  private.pem — приватный ключ, им бот подписывает токены (RS256)
  jwks.json   — публичный JWK Set, его читает Grafana (GF_AUTH_JWT_JWK_SET_FILE)

Идемпотентен: если ключ уже есть — ничего не делает.
"""

import base64
import json
import os
import sys

JWT_DIR = os.environ.get("JWT_DIR", "/jwt")
KID = "dvoretskii-bot-1"


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> int:
    private_path = os.path.join(JWT_DIR, "private.pem")
    jwks_path = os.path.join(JWT_DIR, "jwks.json")
    if os.path.exists(private_path) and os.path.exists(jwks_path):
        print("JWT keys already exist, skipping")
        return 0

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": KID,
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }

    os.makedirs(JWT_DIR, exist_ok=True)
    with open(private_path, "wb") as f:
        f.write(pem)
    os.chmod(private_path, 0o600)
    with open(jwks_path, "w") as f:
        json.dump(jwks, f)
    print(f"Generated {private_path} and {jwks_path} (kid={KID})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
