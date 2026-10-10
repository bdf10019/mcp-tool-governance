from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_token(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=actual_salt, n=2**14, r=8, p=1)
    return actual_salt.hex(), digest.hex()


def password_matches(password: str, salt_hex: str, expected_hex: str) -> bool:
    _, actual = password_hash(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(actual, expected_hex)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

