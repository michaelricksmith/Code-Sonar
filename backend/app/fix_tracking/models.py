"""FixAttempt — one copied fix prompt and its verification state.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FixAttempt:
    """A prompt-first fix in flight.

    ``verified_at`` is None while the fix is in progress. It is set when a
    rescan newer than ``copied_at`` no longer contains the finding, which
    is the definition of a verified fix.
    """

    attempt_id: str
    user_id: str
    repository_id: str
    finding_id: str
    rule_id: str
    file_path: str
    copied_at: str
    scan_id: str | None = None
    verified_at: str | None = None
    verified_scan_id: str | None = None
    score_delta: int | None = None

    @property
    def verified(self) -> bool:
        return self.verified_at is not None

    @property
    def finding_key(self) -> tuple[str, str]:
        """Match key used against scan findings: (rule_id, file_path)."""
        return (self.rule_id, self.file_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "user_id": self.user_id,
            "repository_id": self.repository_id,
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "file_path": self.file_path,
            "copied_at": self.copied_at,
            "scan_id": self.scan_id,
            "verified_at": self.verified_at,
            "verified_scan_id": self.verified_scan_id,
            "score_delta": self.score_delta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FixAttempt":
        return cls(
            attempt_id=str(data["attempt_id"]),
            user_id=str(data["user_id"]),
            repository_id=str(data["repository_id"]),
            finding_id=str(data["finding_id"]),
            rule_id=str(data["rule_id"]),
            file_path=str(data["file_path"]),
            copied_at=str(data["copied_at"]),
            scan_id=data.get("scan_id"),
            verified_at=data.get("verified_at"),
            verified_scan_id=data.get("verified_scan_id"),
            score_delta=data.get("score_delta"),
        )

    @classmethod
    def new(
        cls,
        *,
        user_id: str,
        repository_id: str,
        finding_id: str,
        rule_id: str,
        file_path: str,
        scan_id: str | None = None,
    ) -> "FixAttempt":
        return cls(
            attempt_id=uuid.uuid4().hex,
            user_id=user_id,
            repository_id=repository_id,
            finding_id=finding_id,
            rule_id=rule_id,
            file_path=file_path,
            copied_at=_utcnow_iso(),
            scan_id=scan_id,
        )
