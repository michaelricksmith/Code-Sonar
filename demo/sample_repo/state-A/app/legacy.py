"""Legacy module for the Code Sonar private-beta demo (state A).

This module intentionally contains a function over 50 lines so that
``oversized_functions:over-threshold`` will fire. Combined with the
TODO in ``utils.py``, this gives the demo a clear "moderate findings +
hotspot ranking" story for state A.
"""

from __future__ import annotations


def process_records(records: list[dict]) -> dict:
    """Process a list of records and return aggregated statistics.

    This function is intentionally longer than the analyzer
    threshold (50 lines) so it surfaces as an ``oversized_functions``
    finding. In state B, this function is extended to 75 lines, which
    surfaces as the same finding with WORSENED severity (warning →
    error).
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
    }
