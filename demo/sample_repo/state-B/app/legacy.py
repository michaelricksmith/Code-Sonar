"""Legacy module for the Code Sonar private-beta demo (state B).

This module intentionally:
- Splits record aggregation into small, focused helpers so every
  function stays within the complexity threshold.
- Contains a hardcoded AWS access key so that
  ``secrets:aws-access-key`` fires as a NEW finding in drift.
"""

from __future__ import annotations

# Hardcoded AWS access key (intentionally fake-looking — not a real
# credential; the secrets analyzer redacts it in the dashboard).
AWS_ACCESS_KEY_ID = "AKIA0000000000000000"


def _count_statuses(records: list[dict]) -> dict:
    """Count per-status, error, and warning totals across records."""
    counts = {
        "active": 0,
        "inactive": 0,
        "pending": 0,
        "errors": 0,
        "warnings": 0,
    }
    for record in records:
        status = record.get("status", "pending")
        if status == "active":
            counts["active"] += 1
        elif status == "inactive":
            counts["inactive"] += 1
        elif status == "pending":
            counts["pending"] += 1
        if record.get("error"):
            counts["errors"] += 1
        if record.get("warning"):
            counts["warnings"] += 1
    return counts


def _rate(numerator: float, denominator: float) -> float:
    """Return numerator / denominator, or 0.0 when denominator is zero."""
    return numerator / denominator if denominator else 0.0


def _health_score(error_rate: float, warning_rate: float) -> float:
    """Return the aggregate health score, clamped at zero."""
    return max(0.0, 1.0 - error_rate - 0.5 * warning_rate)


def process_records(records: list[dict]) -> dict:
    """Process a list of records and return aggregated statistics.

    Aggregates per-status/error/warning counts, then derives summary
    rates and health metrics from those counts.
    """
    counts = _count_statuses(records)
    total = len(records)
    complete = total - counts["pending"] - counts["errors"]
    error_rate = _rate(counts["errors"], total)
    warning_rate = _rate(counts["warnings"], total)
    return {
        "total": total,
        "active": counts["active"],
        "inactive": counts["inactive"],
        "pending": counts["pending"],
        "errors": counts["errors"],
        "warnings": counts["warnings"],
        "complete": complete,
        "completion_rate": _rate(complete, total),
        "error_rate": error_rate,
        "warning_rate": warning_rate,
        "active_rate": _rate(counts["active"], total),
        "pending_rate": _rate(counts["pending"], total),
        "health_score": _health_score(error_rate, warning_rate),
        "throughput_per_minute": complete / 60.0 if total else 0.0,
    }


def empty_summary() -> dict:
    """Return an empty summary, useful as a default."""
    return {
        "total": 0,
        "active": 0,
        "inactive": 0,
        "pending": 0,
        "errors": 0,
        "warnings": 0,
        "complete": 0,
        "completion_rate": 0.0,
        "error_rate": 0.0,
        "warning_rate": 0.0,
        "active_rate": 0.0,
        "pending_rate": 0.0,
        "health_score": 0.0,
        "throughput_per_minute": 0.0,
    }
