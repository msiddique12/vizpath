"""Utilities for encrypting and decrypting sensitive persisted secrets."""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

ENCRYPTED_SECRET_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    key = (settings.alert_secret_encryption_key or "").strip()
    if not key:
        raise ValueError("ALERT_SECRET_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise ValueError(
            "ALERT_SECRET_ENCRYPTION_KEY must be a valid Fernet key"
        ) from exc


def encrypt_secret_token(secret_token: str | None) -> str | None:
    """Encrypt destination secrets before persisting to the database."""
    if secret_token is None:
        return None
    encrypted = _get_fernet().encrypt(secret_token.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTED_SECRET_PREFIX}{encrypted}"


def decrypt_secret_token(stored_secret: str | None) -> str | None:
    """Decrypt persisted destination secret token.

    Plaintext values without the prefix are treated as legacy records.
    """
    if stored_secret is None:
        return None
    if not stored_secret.startswith(ENCRYPTED_SECRET_PREFIX):
        return stored_secret
    token = stored_secret[len(ENCRYPTED_SECRET_PREFIX) :]
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Encrypted destination secret token is invalid") from exc
