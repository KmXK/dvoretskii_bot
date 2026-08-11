import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from steward.api import auth


def test_validate_oidc_id_token_uses_bundled_key(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    key_data.update({"alg": "RS256", "kid": "test-key"})
    monkeypatch.setattr(auth, "TELEGRAM_OIDC_JWKS", {"keys": [key_data]})
    monkeypatch.setenv("TELEGRAM_LOGIN_CLIENT_ID", "test-client")

    token = jwt.encode(
        {
            "iss": auth.TELEGRAM_OIDC_ISSUER,
            "aud": "test-client",
            "exp": int(time.time()) + 60,
            "sub": "12345",
            "given_name": "Kirill",
            "preferred_username": "kmx",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    user = auth.validate_oidc_id_token(token)

    assert user == {
        "id": 12345,
        "first_name": "Kirill",
        "last_name": "",
        "username": "kmx",
        "photo_url": "",
    }
