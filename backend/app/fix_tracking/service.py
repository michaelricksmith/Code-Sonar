"""Fix-tracking service: verification reconciliation and per-user stats.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.fix_tracking.models import FixAttempt
from app.fix_tracking.runtime import get_fix_attempt_store


def reconcile_verified_fixes(
    repository_id: str,
    new_record: Any,
    history_store: Any,
) -> int:
    """Mark open fix attempts verified when the new scan resolved them.

    An attempt is verified when a scan newer than ``copied_at`` no longer
    contains the finding's ``(rule_id, file_path)`` key. Returns the number
    of attempts marked verified. Never raises: verification is
    best-effort and must not break scan completion.
    """
    try:
        store = get_fix_attempt_store()
        open_attempts = store.list_open(repository_id)
        if not open_attempts:
            return 0
        finding_keys = {
            (str(f.rule_id), str(f.file_path)) for f in new_record.findings or []
        }
        verified = 0
        for attempt in open_attempts:
            if new_record.scanned_at <= attempt.copied_at:
                continue
            if attempt.finding_key in finding_keys:
                continue
            score_delta = _score_delta(history_store, attempt, new_record)
            if store.mark_verified(
                attempt.attempt_id,
                verified_at=new_record.scanned_at,
                verified_scan_id=new_record.scan_id,
                score_delta=score_delta,
            ):
                verified += 1
        return verified
    except Exception:
        return 0


def _score_delta(history_store: Any, attempt: FixAttempt, new_record: Any) -> int | None:
    """Score change between the attempt's origin scan and the verifying scan."""
    if not attempt.scan_id:
        return None
    try:
        before = history_store.get(attempt.scan_id)
    except Exception:
        return None
    if before is None:
        return None
    delta: int = new_record.score - before.score
    return delta


def _parse_week_start(iso_ts: str) -> str | None:
    """Monday (ISO date) of the week containing the timestamp."""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return monday.date().isoformat()


def user_fix_stats(user_id: str) -> dict[str, Any]:
    """Per-user fix stats for reports, streaks, and the weekly digest."""
    store = get_fix_attempt_store()
    attempts = store.list_by_user(user_id)
    verified = [a for a in attempts if a.verified]
    in_progress = [a for a in attempts if not a.verified]

    this_week_start = _parse_week_start(datetime.now(timezone.utc).isoformat())
    verified_this_week = sum(
        1 for a in verified if _parse_week_start(a.verified_at or "") == this_week_start
    )

    by_week: dict[str, int] = {}
    for attempt in verified:
        week = _parse_week_start(attempt.verified_at or "")
        if week:
            by_week[week] = by_week.get(week, 0) + 1
    best_week_start = max(by_week, key=lambda w: by_week[w], default=None)

    per_repo: dict[str, dict[str, int]] = {}
    for attempt in attempts:
        entry = per_repo.setdefault(
            attempt.repository_id, {"verified": 0, "in_progress": 0}
        )
        if attempt.verified:
            entry["verified"] += 1
        else:
            entry["in_progress"] += 1

    return {
        "user_id": user_id,
        "total_verified": len(verified),
        "verified_this_week": verified_this_week,
        "best_week": (
            {"week_start": best_week_start, "count": by_week[best_week_start]}
            if best_week_start
            else None
        ),
        "in_progress": len(in_progress),
        "per_repo": [
            {"repository_id": repo_id, **counts}
            for repo_id, counts in sorted(per_repo.items())
        ],
    }
