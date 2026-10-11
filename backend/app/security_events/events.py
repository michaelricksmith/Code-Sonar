"""Security event logging: logins, 2FA, admin actions, device alerts.

Copyright © 2026 Michael Smith. All rights reserved.

Events are append-only. Device fingerprints are SHA-256 hashes of the
user agent + IP — enough to recognize a returning device without
storing raw identifiers in the hot path. A login from an unseen device
emits a ``new_device_login`` event; the UI surfaces it and email
delivery hooks into the digest Resend client when configured.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

# Event types. Keep the set small and stable; metadata carries detail.
LOGIN_SUCCESS = "login_success"
LOGIN_FAILURE = "login_failure"
LOGOUT = "logout"
TWO_FA_ENROLLED = "2fa_enrolled"
TWO_FA_DISABLED = "2fa_disabled"
TWO_FA_FAILED = "2fa_failed"
SESSION_REVOKED = "session_revoked"
ADMIN_ACTION = "admin_action"
NEW_DEVICE_LOGIN = "new_device_login"


@dataclass
class SecurityEvent:
    event_id: str
    user_id: str | None
    event_type: str
    created_at: str
    ip_address: str | None = None
    user_agent: str | None = None
    device_fingerprint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SecurityEventStore(Protocol):
    def append(self, event: SecurityEvent) -> None: ...
    def list_for_user(self, user_id: str, limit: int = 50) -> list[SecurityEvent]: ...
    def known_devices(self, user_id: str) -> set[str]: ...


class InMemorySecurityEventStore:
    def __init__(self) -> None:
        self._events: list[SecurityEvent] = []

    def append(self, event: SecurityEvent) -> None:
        self._events.append(event)

    def list_for_user(self, user_id: str, limit: int = 50) -> list[SecurityEvent]:
        return [e for e in self._events if e.user_id == user_id][-limit:]

    def known_devices(self, user_id: str) -> set[str]:
        return {
            e.device_fingerprint
            for e in self._events
            if e.user_id == user_id
            and e.event_type == LOGIN_SUCCESS
            and e.device_fingerprint
        }


_store: SecurityEventStore = InMemorySecurityEventStore()


def get_security_event_store() -> SecurityEventStore:
    return _store


def set_security_event_store(store: SecurityEventStore) -> None:
    global _store
    _store = store


def device_fingerprint(user_agent: str | None, ip_address: str | None) -> str:
    material = f"{user_agent or ''}|{ip_address or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(
    event_type: str,
    *,
    user_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SecurityEvent:
    """Append a security event. Never raises: logging must not break auth."""
    try:
        event = SecurityEvent(
            event_id="se_" + uuid.uuid4().hex[:24],
            user_id=user_id,
            event_type=event_type,
            created_at=_utcnow_iso(),
            ip_address=ip_address,
            user_agent=(user_agent or "")[:512],
            device_fingerprint=(
                device_fingerprint(user_agent, ip_address)
                if user_agent or ip_address
                else None
            ),
            metadata=dict(metadata or {}),
        )
        get_security_event_store().append(event)
        return event
    except Exception:
        return SecurityEvent(
            event_id="se_dropped",
            user_id=user_id,
            event_type=event_type,
            created_at=_utcnow_iso(),
        )


def log_login_success(
    user_id: str,
    *,
    ip_address: str | None,
    user_agent: str | None,
    provider: str,
    with_2fa: bool = False,
) -> bool:
    """Log a login. Returns True when the device is new for this user."""
    store = get_security_event_store()
    fingerprint = device_fingerprint(user_agent, ip_address)
    is_new_device = fingerprint not in store.known_devices(user_id)
    log_event(
        LOGIN_SUCCESS,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"provider": provider, "with_2fa": with_2fa},
    )
    if is_new_device:
        log_event(
            NEW_DEVICE_LOGIN,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"provider": provider},
        )
    return is_new_device
