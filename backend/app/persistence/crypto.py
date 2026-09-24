"""Envelope-encryption provider contracts for sensitive persistence fields."""

from __future__ import annotations

import base64
import os
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EncryptionProvider(Protocol):
    provider_name: str
    production_safe: bool

    def encrypt(self, plaintext: str, *, aad: bytes) -> str: ...
    def decrypt(self, ciphertext: str, *, aad: bytes) -> str: ...


class LocalDevelopmentEncryptionProvider:
    """AES-GCM provider permitted only for explicit local development."""
    provider_name = "local-aes-gcm"
    production_safe = False

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Local encryption key must be exactly 32 bytes")
        self._cipher = AESGCM(key)

    @classmethod
    def from_env(cls) -> "LocalDevelopmentEncryptionProvider":
        raw = os.environ.get("CODESONAR_LOCAL_ENCRYPTION_KEY", "").strip()
        if not raw:
            raise RuntimeError("CODESONAR_LOCAL_ENCRYPTION_KEY is required for SQL storage")
        try:
            key = base64.urlsafe_b64decode(raw)
        except Exception as exc:
            raise RuntimeError("CODESONAR_LOCAL_ENCRYPTION_KEY must be base64") from exc
        return cls(key)

    def encrypt(self, plaintext: str, *, aad: bytes) -> str:
        nonce = os.urandom(12)
        payload = nonce + self._cipher.encrypt(nonce, plaintext.encode(), aad)
        return base64.urlsafe_b64encode(payload).decode()

    def decrypt(self, ciphertext: str, *, aad: bytes) -> str:
        payload = base64.urlsafe_b64decode(ciphertext)
        return self._cipher.decrypt(payload[:12], payload[12:], aad).decode()


class EnvKeyEncryptionProvider:
    """AES-GCM provider keyed by an environment secret.

    Production-safe: the 32-byte key comes from the
    ``CODESONAR_ENCRYPTION_KEY`` secret env var (base64-encoded),
    which the hosting platform encrypts at rest. The key must be
    generated once (``openssl rand -base64 32``) and never committed
    to the repo — losing it renders encrypted fields unrecoverable,
    so back it up with the database credentials.
    """

    provider_name = "env-aes-gcm"
    production_safe = True

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Encryption key must be exactly 32 bytes")
        self._cipher = AESGCM(key)

    @classmethod
    def from_env(cls) -> "EnvKeyEncryptionProvider":
        raw = os.environ.get("CODESONAR_ENCRYPTION_KEY", "").strip()
        if not raw:
            raise RuntimeError("CODESONAR_ENCRYPTION_KEY is required for SQL storage")
        try:
            key = base64.urlsafe_b64decode(raw)
        except Exception as exc:
            raise RuntimeError("CODESONAR_ENCRYPTION_KEY must be base64") from exc
        return cls(key)

    def encrypt(self, plaintext: str, *, aad: bytes) -> str:
        nonce = os.urandom(12)
        payload = nonce + self._cipher.encrypt(nonce, plaintext.encode(), aad)
        return base64.urlsafe_b64encode(payload).decode()

    def decrypt(self, ciphertext: str, *, aad: bytes) -> str:
        payload = base64.urlsafe_b64decode(ciphertext)
        return self._cipher.decrypt(payload[:12], payload[12:], aad).decode()


def checkout_path_aad(tenant_id: str, project_id: str) -> bytes:
    return f"code-sonar:v1:{tenant_id}:projects:{project_id}:checkout_path".encode()
