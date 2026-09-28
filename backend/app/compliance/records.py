"""Append-only compliance records.

Each record is ``(user_id, record_type, payload, created_at)``. Records are
never updated or deleted in place — new events append new records — so the
history doubles as an audit trail.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

# Record types.
AUTORENEW_CONSENT = "autorenew_consent"  # express affirmative consent to auto-renewal
CANCELLATION = "cancellation"  # subscription cancellation (requested / completed)
MARKETING_CONSENT = "marketing_consent"  # opt-in / opt-out of marketing email
AGE_GATE = "age_gate"  # age-gate confirmation (bracket 13-17 or 18+)
GPC_OPTOUT = "gpc_optout"  # Global Privacy Control signal honored
ANNUAL_REMINDER_SENT = "annual_reminder_sent"  # CA AB 2863 annual renewal reminder
FEE_CHANGE_NOTICE = "fee_change_notice"  # advance notice of a price change


@dataclass(frozen=True, slots=True)
class ComplianceRecord:
    record_id: str
    user_id: str
    record_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


class ComplianceRecordStore(Protocol):
    """Structural interface; JSON and SQL stores both satisfy it."""

    def append(
        self, *, user_id: str, record_type: str, payload: dict[str, Any] | None = None
    ) -> ComplianceRecord:
        """Append a record. Never raises for duplicate content."""
        ...

    def latest(
        self, user_id: str, record_type: str
    ) -> ComplianceRecord | None:
        """Return the most recent record of this type for the user."""
        ...

    def history(
        self, user_id: str, record_type: str | None = None
    ) -> list[ComplianceRecord]:
        """All records for the user (optionally filtered by type), oldest first."""
        ...


def _utcnow_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _default_path() -> Path:
    override = os.environ.get("SONAR_COMPLIANCE_RECORDS_PATH", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".code-sonar" / "compliance-records.json"


class JsonComplianceRecordStore:
    """Local JSON compliance record store (mode 0600), mirroring OAuthUserStore.

    Ephemeral on hosted deployments — production uses the SQL store through
    the transactional persistence unit of work.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self._lock = RLock()

    def _load(self) -> list[ComplianceRecord]:
        if not self.path.exists():
            return []
        items = json.loads(self.path.read_text(encoding="utf-8"))
        return [ComplianceRecord(**item) for item in items]

    def _save(self, records: list[ComplianceRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([asdict(r) for r in records], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.path)

    def append(
        self, *, user_id: str, record_type: str, payload: dict[str, Any] | None = None
    ) -> ComplianceRecord:
        record = ComplianceRecord(
            record_id=uuid.uuid4().hex,
            user_id=user_id,
            record_type=record_type,
            payload=dict(payload or {}),
            created_at=_utcnow_iso(),
        )
        with self._lock:
            records = self._load()
            records.append(record)
            self._save(records)
        return record

    def latest(self, user_id: str, record_type: str) -> ComplianceRecord | None:
        with self._lock:
            matches = [
                r
                for r in self._load()
                if r.user_id == user_id and r.record_type == record_type
            ]
        return matches[-1] if matches else None

    def history(
        self, user_id: str, record_type: str | None = None
    ) -> list[ComplianceRecord]:
        with self._lock:
            return [
                r
                for r in self._load()
                if r.user_id == user_id
                and (record_type is None or r.record_type == record_type)
            ]


_compliance_store: ComplianceRecordStore = JsonComplianceRecordStore()


def get_compliance_store() -> ComplianceRecordStore:
    return _compliance_store


def set_compliance_store(store: ComplianceRecordStore) -> None:
    global _compliance_store
    _compliance_store = store
