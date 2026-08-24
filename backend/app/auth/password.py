"""Password hashing and verification using Argon2."""

from __future__ import annotations

import secrets
from typing import Final

import argon2
from argon2 import PasswordHasher

# Argon2id parameters - tuned for security and reasonable performance
# memory_cost: 64 MB, time_cost: 3 iterations, parallelism: 4
# These are strong defaults per OWASP recommendations
_ARGON2_MEMORY_COST: Final[int] = 65536  # 64 MB
_ARGON2_TIME_COST: Final[int] = 3
_ARGON2_PARALLELISM: Final[int] = 4
_ARGON2_HASH_LEN: Final[int] = 32
_ARGON2_SALT_LEN: Final[int] = 16

# Singleton hasher instance
_hasher: PasswordHasher = PasswordHasher(
    time_cost=_ARGON2_TIME_COST,
    memory_cost=_ARGON2_MEMORY_COST,
    parallelism=_ARGON2_PARALLELISM,
    hash_len=_ARGON2_HASH_LEN,
    salt_len=_ARGON2_SALT_LEN,
    type=argon2.Type.ID,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id.

    Returns the encoded hash string (includes salt, parameters, and hash).
    """
    if not password:
        raise ValueError("Password cannot be empty")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2id hash.

    Returns True if the password matches, False otherwise.
    """
    if not password or not password_hash:
        return False
    try:
        _hasher.verify(password_hash, password)
        return True
    except argon2.exceptions.VerifyMismatchError:
        return False
    except argon2.exceptions.InvalidHashError:
        # Hash format is invalid or uses unsupported parameters
        return False


def needs_rehash(password_hash: str) -> bool:
    """Check if a hash needs to be rehashed with current parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except argon2.exceptions.InvalidHashError:
        return True


def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token.

    Returns a URL-safe base64-encoded string.
    """
    return secrets.token_urlsafe(length)