"""Legacy module for the Code Sonar private-beta demo (state B).

This module intentionally:
- Contains a function over 70 lines (grown from 60 in state A)
  so that ``oversized_functions:over-threshold`` WORSENS in drift.
- Contains a hardcoded AWS access key so that
  ``secrets:aws-access-key`` fires as a NEW finding in drift.
"""

from __future__ import annotations

# Hardcoded AWS access key (intentionally fake-looking — not a real
# credential; the secrets analyzer redacts it in the dashboard).
AWS_ACCESS_KEY_ID = "AKIA0000000000000000"


def process_records(records: list[dict]) -> dict:
    """Process a list of records and return aggregated statistics.

    Same function as state A but extended with extra summary fields
    so it crosses the 70-line ``oversized_functions`` threshold
    (warning → error). The drift demo will surface this as a
    WORSENED finding on the same ``finding_id``.
    """
    summary = {
        "total": len(records),
        "active": 0,
        "inactive": 0,
        "pending": 0,
        "errors": 0,
        "warnings": 0,
    }
    for record in records:
        status = record.get("status", "pending")
        if status == "active":
            summary["active"] += 1
        elif status == "inactive":
            summary["inactive"] += 1
        elif status == "pending":
            summary["pending"] += 1
        if record.get("error"):
            summary["errors"] += 1
        if record.get("warning"):
            summary["warnings"] += 1
    summary["complete"] = (
        summary["total"] - summary["pending"] - summary["errors"]
    )
    summary["completion_rate"] = (
        summary["complete"] / summary["total"] if summary["total"] else 0.0
    )
    summary["error_rate"] = (
        summary["errors"] / summary["total"] if summary["total"] else 0.0
    )
    summary["warning_rate"] = (
        summary["warnings"] / summary["total"] if summary["total"] else 0.0
    )
    # State-B additions: extra aggregate metrics that push the
    # function past the 70-line threshold so it WORSENS in drift.
    summary["active_rate"] = (
        summary["active"] / summary["total"] if summary["total"] else 0.0
    )
    summary["pending_rate"] = (
        summary["pending"] / summary["total"] if summary["total"] else 0.0
    )
    summary["health_score"] = max(
        0.0,
        1.0 - summary["error_rate"] - 0.5 * summary["warning_rate"],
    )
    summary["throughput_per_minute"] = (
        summary["complete"] / 60.0 if summary["total"] else 0.0
    )
    return summary


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
