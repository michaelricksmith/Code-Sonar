"""TOTP (RFC 6238) implementation for two-factor authentication.

Copyright © 2026 Michael Smith. All rights reserved.

Implemented on the standard library (hmac/hashlib/base64/struct) so
2FA has no new cryptographic dependency. Secrets are 160-bit,
base32-encoded without padding, matching what authenticator apps
expect.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

_TIME_STEP = 30
_DIGITS = 6
_WINDOW = 1  # Accept one step of clock skew in either direction.


def generate_secret() -> str:
    """A fresh 160-bit TOTP secret, base32-encoded."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret.upper())
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**_DIGITS)).zfill(_DIGITS)


def totp_code(secret: str, for_time: float | None = None) -> str:
    """The current TOTP code for a secret."""
    counter = int((for_time if for_time is not None else time.time()) // _TIME_STEP)
    return _hotp(secret, counter)


def verify_code(secret: str, code: str, for_time: float | None = None) -> bool:
    """Verify a code, accepting one time-step of clock skew either way."""
    code = code.strip().replace(" ", "")
    if len(code) != _DIGITS or not code.isdigit():
        return False
    now = for_time if for_time is not None else time.time()
    counter = int(now // _TIME_STEP)
    for delta in range(-_WINDOW, _WINDOW + 1):
        if hmac.compare_digest(_hotp(secret, counter + delta), code):
            return True
    return False


def otpauth_uri(secret: str, account: str, issuer: str = "Code Sonar") -> str:
    """The otpauth:// URI authenticator apps scan."""
    label = quote(f"{issuer}:{account}")
    params = f"secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    return f"otpauth://totp/{label}?{params}"


def qr_svg(otpauth_uri: str) -> str:
    """A QR code for the otpauth URI as an inline SVG string."""
    import qrcode  # type: ignore[import-untyped]
    import qrcode.image.svg  # type: ignore[import-untyped]

    qr = qrcode.QRCode(image_factory=qrcode.image.svg.SvgImage)
    qr.add_data(otpauth_uri)
    qr.make(fit=True)
    svg: str = qr.make_image().to_string().decode("utf-8")
    return svg


def generate_backup_codes(count: int = 8) -> list[str]:
    """Single-use backup codes, shown once at enrollment."""
    return [secrets.token_hex(4).upper() for _ in range(count)]


def hash_backup_code(code: str) -> str:
    normalized = code.strip().replace(" ", "").replace("-", "").upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
