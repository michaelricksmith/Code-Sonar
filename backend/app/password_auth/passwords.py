"""Password hashing (scrypt) and HaveIBeenPwned breach checking.

Copyright © 2026 Michael Smith. All rights reserved.

Passwords are hashed with scrypt (N=2^15, r=8, p=1, 32-byte output) —
memory-hard, NIST-approved, stdlib-only. The breach check uses the
HaveIBeenPwned k-anonymity API: only the first 5 hex chars of the
SHA-1 ever leave the server.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

import httpx

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 32

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"
_HIBP_TIMEOUT = 10.0

MIN_PASSWORD_LENGTH = 8


@dataclass
class PasswordPolicyViolation:
    reason: str


def validate_password(password: str) -> PasswordPolicyViolation | None:
    """Basic policy: length. Breach checking is separate (needs network)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return PasswordPolicyViolation(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > 256:
        return PasswordPolicyViolation("Password is too long.")
    return None


def hash_password(password: str) -> str:
    """scrypt hash in a PHC-style string: $scrypt$n=16384,r=8,p=1$<salt>$<hash>."""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LEN,
    )
    import base64

    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"$scrypt$n={_SCRYPT_N},r={_SCRYPT_R},p={_SCRYPT_P}${salt_b64}${hash_b64}"


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification. Unknown formats verify as False."""
    try:
        import base64

        parts = password_hash.split("$")
        if len(parts) != 5 or parts[1] != "scrypt":
            return False
        params = dict(kv.split("=") for kv in parts[2].split(","))
        salt = base64.b64decode(parts[3])
        expected = base64.b64decode(parts[4])
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(params["n"]),
            r=int(params["r"]),
            p=int(params["p"]),
            dklen=len(expected),
        )
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def is_password_breached(password: str) -> bool | None:
    """Check HIBP. Returns True/False, or None when the API is unreachable.

    A None result means "unknown" — callers should allow the password
    but log the outage, rather than blocking signup on HIBP downtime.
    """
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    try:
        response = httpx.get(
            _HIBP_RANGE_URL + prefix,
            timeout=_HIBP_TIMEOUT,
            headers={"User-Agent": "Code-Sonar-Security-Check"},
        )
        if response.status_code != 200:
            return None
        for line in response.text.splitlines():
            if line.split(":")[0].strip().upper() == suffix:
                return True
        return False
    except Exception:
        return None


def check_password_breached_or_raise(password: str) -> None:
    """Raise HTTPException when the password appears in a breach."""
    from fastapi import HTTPException

    breached = is_password_breached(password)
    if breached is True:
        raise HTTPException(
            status_code=400,
            detail=(
                "This password has appeared in a data breach. "
                "Please choose a different one."
            ),
        )
    # None (API unreachable) fails open; the outage is logged by the caller.
