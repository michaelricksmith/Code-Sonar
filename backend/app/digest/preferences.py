"""Digest email preferences: runtime registry + one-tap unsubscribe tokens.

Copyright © 2026 Michael Smith. All rights reserved.

Unsubscribe links carry an HMAC-signed token over the user id, so no
lookup table is needed and tokens can't be forged. The signing secret
falls back to a clearly-labeled dev value when EMAIL_SIGNING_SECRET is
unset — production must set it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Protocol


class EmailPreferenceStore(Protocol):
    def is_digest_enabled(self, user_id: str) -> bool: ...
    def set_digest_enabled(self, user_id: str, enabled: bool) -> None: ...


class InMemoryEmailPreferenceStore:
    """Default for tests and non-SQL deployments. Opted in unless set."""

    def __init__(self) -> None:
        self._disabled: set[str] = set()

    def is_digest_enabled(self, user_id: str) -> bool:
        return user_id not in self._disabled

    def set_digest_enabled(self, user_id: str, enabled: bool) -> None:
        if enabled:
            self._disabled.discard(user_id)
        else:
            self._disabled.add(user_id)


_store: EmailPreferenceStore = InMemoryEmailPreferenceStore()


def get_email_preference_store() -> EmailPreferenceStore:
    return _store


def set_email_preference_store(store: EmailPreferenceStore) -> None:
    global _store
    _store = store


def _signing_secret() -> bytes:
    secret = os.environ.get("EMAIL_SIGNING_SECRET", "").strip()
    if not secret:
        secret = "dev-only-email-signing-secret"
    return secret.encode("utf-8")


def unsubscribe_token(user_id: str) -> str:
    """One-tap token: base64(user_id) + '.' + hex HMAC."""
    raw = base64.urlsafe_b64encode(user_id.encode("utf-8")).decode("ascii")
    sig = hmac.new(_signing_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_unsubscribe_token(token: str) -> str | None:
    """Return the user id when the token is valid, else None."""
    try:
        raw, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(
        _signing_secret(), raw.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
    except Exception:
        return None
