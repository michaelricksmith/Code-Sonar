"""TOTP two-factor authentication: storage + enrollment/verification logic.

Copyright © 2026 Michael Smith. All rights reserved.

Secrets are encrypted at rest (AES-GCM via the persistence encryption
provider). Backup codes are SHA-256 hashed, single-use. Failed attempts
lock the 2FA challenge for 15 minutes after 5 failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.twofa import totp

_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15


@dataclass
class TwoFactorRecord:
    user_id: str
    enabled: bool = False
    enrolled_at: str | None = None
    backup_code_hashes: list[str] = field(default_factory=list)
    failed_attempts: int = 0
    locked_until: str | None = None
    # The decrypted secret lives here only in memory, never persisted plain.
    _secret: str | None = None


class TwoFactorStore(Protocol):
    def get(self, user_id: str) -> TwoFactorRecord | None: ...
    def save_pending(self, user_id: str, secret: str) -> None: ...
    def enable(self, user_id: str, backup_code_hashes: list[str]) -> None: ...
    def disable(self, user_id: str) -> None: ...
    def record_failure(self, user_id: str) -> None: ...
    def reset_failures(self, user_id: str) -> None: ...
    def consume_backup_code(self, user_id: str, code_hash: str) -> bool: ...
    def get_secret(self, user_id: str) -> str | None: ...


class InMemoryTwoFactorStore:
    """Default for tests and non-SQL deployments."""

    def __init__(self) -> None:
        self._records: dict[str, TwoFactorRecord] = {}
        self._secrets: dict[str, str] = {}

    def get(self, user_id: str) -> TwoFactorRecord | None:
        return self._records.get(user_id)

    def save_pending(self, user_id: str, secret: str) -> None:
        self._secrets[user_id] = secret
        record = self._records.get(user_id) or TwoFactorRecord(user_id=user_id)
        record.enabled = False
        self._records[user_id] = record

    def enable(self, user_id: str, backup_code_hashes: list[str]) -> None:
        record = self._records.get(user_id) or TwoFactorRecord(user_id=user_id)
        record.enabled = True
        record.enrolled_at = datetime.now(timezone.utc).isoformat()
        record.backup_code_hashes = list(backup_code_hashes)
        record.failed_attempts = 0
        record.locked_until = None
        self._records[user_id] = record

    def disable(self, user_id: str) -> None:
        self._records.pop(user_id, None)
        self._secrets.pop(user_id, None)

    def record_failure(self, user_id: str) -> None:
        record = self._records.get(user_id) or TwoFactorRecord(user_id=user_id)
        record.failed_attempts += 1
        if record.failed_attempts >= _MAX_FAILED_ATTEMPTS:
            record.locked_until = (
                datetime.now(timezone.utc) + timedelta(minutes=_LOCKOUT_MINUTES)
            ).isoformat()
        self._records[user_id] = record

    def reset_failures(self, user_id: str) -> None:
        record = self._records.get(user_id)
        if record:
            record.failed_attempts = 0
            record.locked_until = None

    def consume_backup_code(self, user_id: str, code_hash: str) -> bool:
        record = self._records.get(user_id)
        if not record or code_hash not in record.backup_code_hashes:
            return False
        record.backup_code_hashes.remove(code_hash)
        return True

    def get_secret(self, user_id: str) -> str | None:
        return self._secrets.get(user_id)


_store: TwoFactorStore = InMemoryTwoFactorStore()


def get_two_factor_store() -> TwoFactorStore:
    return _store


def set_two_factor_store(store: TwoFactorStore) -> None:
    global _store
    _store = store


def is_locked(record: TwoFactorRecord | None) -> bool:
    if record is None or not record.locked_until:
        return False
    try:
        locked_until = datetime.fromisoformat(record.locked_until)
    except ValueError:
        return False
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < locked_until


def verify_login_code(user_id: str, code: str) -> tuple[bool, str]:
    """Verify a TOTP code or backup code. Returns (ok, method)."""
    store = get_two_factor_store()
    record = store.get(user_id)
    if record is None or not record.enabled:
        return False, "not_enrolled"
    if is_locked(record):
        return False, "locked"
    secret = store.get_secret(user_id)
    if secret and totp.verify_code(secret, code):
        store.reset_failures(user_id)
        return True, "totp"
    code_hash = totp.hash_backup_code(code)
    if store.consume_backup_code(user_id, code_hash):
        store.reset_failures(user_id)
        return True, "backup_code"
    store.record_failure(user_id)
    from app.security_events.events import TWO_FA_FAILED, log_event

    log_event(TWO_FA_FAILED, user_id=user_id)
    return False, "invalid"
