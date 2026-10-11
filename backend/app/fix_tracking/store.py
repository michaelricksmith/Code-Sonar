"""Fix-attempt stores.

Copyright © 2026 Michael Smith. All rights reserved.

``InMemoryFixAttemptStore`` is the default for tests and for deployments
without SQL persistence. Production wires ``SqlFixAttemptStore`` (in
``app.persistence.repositories``) at startup.
"""

from __future__ import annotations

from typing import Protocol

from app.fix_tracking.models import FixAttempt


class FixAttemptStore(Protocol):
    """Persistence contract for fix attempts."""

    def append(self, attempt: FixAttempt) -> None: ...
    def list_open(self, repository_id: str) -> list[FixAttempt]: ...
    def list_by_user(
        self, user_id: str, *, verified_only: bool = False
    ) -> list[FixAttempt]: ...
    def mark_verified(
        self,
        attempt_id: str,
        *,
        verified_at: str,
        verified_scan_id: str,
        score_delta: int | None,
    ) -> bool: ...


class InMemoryFixAttemptStore:
    """Process-local store. Tests use this; production uses SQL."""

    def __init__(self) -> None:
        self._attempts: dict[str, FixAttempt] = {}

    def append(self, attempt: FixAttempt) -> None:
        self._attempts[attempt.attempt_id] = attempt

    def list_open(self, repository_id: str) -> list[FixAttempt]:
        return sorted(
            (
                a
                for a in self._attempts.values()
                if a.repository_id == repository_id and not a.verified
            ),
            key=lambda a: (a.copied_at, a.attempt_id),
        )

    def list_by_user(
        self, user_id: str, *, verified_only: bool = False
    ) -> list[FixAttempt]:
        return sorted(
            (
                a
                for a in self._attempts.values()
                if a.user_id == user_id and (a.verified or not verified_only)
            ),
            key=lambda a: (a.copied_at, a.attempt_id),
        )

    def mark_verified(
        self,
        attempt_id: str,
        *,
        verified_at: str,
        verified_scan_id: str,
        score_delta: int | None,
    ) -> bool:
        attempt = self._attempts.get(attempt_id)
        if attempt is None or attempt.verified:
            return False
        attempt.verified_at = verified_at
        attempt.verified_scan_id = verified_scan_id
        attempt.score_delta = score_delta
        return True
