"""Churn signals and tailored nudges for retention Phase 4.

Copyright © 2026 Michael Smith. All rights reserved.

Signals are computed from existing stored state only:

- ``scanned_once_no_fix``: the user scanned but never copied a fix prompt.
- ``fix_no_rescan``: the user copied a fix prompt but never rescanned after.
- ``dormant``: three or more historical scans, none in the last 14 days.

Every nudge references the user's actual repo state. No generic
"we miss you" messages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.fix_tracking.runtime import get_fix_attempt_store

_DORMANT_DAYS = 14
_DORMANT_MIN_SCANS = 3


def _parse_ts(iso_ts: str | None) -> datetime | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def user_churn_signals(user_id: str, history_store: Any) -> list[dict[str, Any]]:
    """Churn signals for one user, most urgent first."""
    signals: list[dict[str, Any]] = []
    records = [
        r for r in history_store.load_all() if r.owner_user_id == user_id
    ]
    if not records:
        return signals

    try:
        attempts = get_fix_attempt_store().list_by_user(user_id)
    except Exception:
        attempts = []
    copied = [a for a in attempts]

    records.sort(key=lambda r: r.scanned_at)
    latest = records[-1]
    latest_ts = _parse_ts(latest.scanned_at)
    now = datetime.now(timezone.utc)

    # Dormant: engaged before (3+ scans), quiet for 14+ days.
    if (
        len(records) >= _DORMANT_MIN_SCANS
        and latest_ts is not None
        and (now - latest_ts).days >= _DORMANT_DAYS
    ):
        signals.append(
            {
                "signal": "dormant",
                "days_since_scan": (now - latest_ts).days,
                "repository_label": latest.repository_slug
                or latest.repository_path.rsplit("/", 1)[-1],
                "last_score": latest.score,
                "open_issues": latest.finding_count,
            }
        )

    # Fix prompt copied but no rescan since the copy.
    for attempt in copied:
        if attempt.verified:
            continue
        copied_ts = _parse_ts(attempt.copied_at)
        if copied_ts is None:
            continue
        rescanned = any(
            (_parse_ts(r.scanned_at) or copied_ts) > copied_ts for r in records
        )
        if not rescanned:
            signals.append(
                {
                    "signal": "fix_no_rescan",
                    "rule_id": attempt.rule_id,
                    "file_path": attempt.file_path,
                    "copied_at": attempt.copied_at,
                }
            )
            break  # One nudge per user; the most recent stuck fix.

    # Scanned but never started a fix.
    if records and not copied:
        signals.append(
            {
                "signal": "scanned_once_no_fix",
                "scan_count": len(records),
                "open_issues": latest.finding_count,
                "repository_label": latest.repository_slug
                or latest.repository_path.rsplit("/", 1)[-1],
            }
        )

    return signals


def generate_nudge(user_id: str, history_store: Any) -> dict[str, Any] | None:
    """One tailored nudge for the user's most urgent signal, or None."""
    signals = user_churn_signals(user_id, history_store)
    if not signals:
        return None
    signal = signals[0]
    kind = signal["signal"]
    if kind == "dormant":
        text = (
            f"{signal['repository_label']} last scored {signal['last_score']} "
            f"{signal['days_since_scan']} days ago with "
            f"{signal['open_issues']} open "
            f"{'issue' if signal['open_issues'] == 1 else 'issues'}. "
            "Push your latest changes and Code Sonar will rescan automatically."
        )
    elif kind == "fix_no_rescan":
        text = (
            f"You copied a fix prompt for {signal['file_path']} "
            f"({signal['rule_id']}) but never rescanned. "
            "Rescan to verify the fix landed and watch your score move."
        )
    elif kind == "scanned_once_no_fix":
        text = (
            f"{signal['repository_label']} has {signal['open_issues']} open "
            f"{'issue' if signal['open_issues'] == 1 else 'issues'}. "
            "Generate a fix prompt for the top one — it takes a minute, "
            "and the rescan verifies it worked."
        )
    else:
        return None
    return {"signal": kind, "text": text, "detail": signal}
