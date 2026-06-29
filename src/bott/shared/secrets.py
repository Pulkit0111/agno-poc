"""SecretBox — symmetric encryption for secrets/tokens at rest.

Key from env in dev (BOTT_SECRET_KEY); swap `from_env` for a vault/KMS lookup in prod.
Connector tokens and app secrets are stored as ciphertext produced here."""

from __future__ import annotations

from cryptography.fernet import Fernet

from bott.shared.config import bott_secret_key


def generate_key() -> str:
    """A fresh urlsafe-base64 Fernet key (store in BOTT_SECRET_KEY)."""
    return Fernet.generate_key().decode("utf-8")


class SecretBox:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)

    @classmethod
    def from_env(cls) -> "SecretBox":
        key = bott_secret_key()
        if not key:
            raise RuntimeError("BOTT_SECRET_KEY is not set — cannot encrypt secrets at rest.")
        return cls(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
