"""Drift engine for Code Sonar (Checkpoint 6, Lane 2).

Pure-function drift comparison between two ``ScanRecord`` instances.

The engine:

- Classifies each finding as ``NEW``, ``RESOLVED``, ``PERSISTENT``,
  ``WORSENED``, or ``IMPROVED`` using ``finding_id`` as the join key.
- Returns an aggregate ``DriftSummary`` (score_delta, debt_delta,
  finding_delta, classification counts).
- Returns per-category, per-analyzer, per-severity drill-downs.

Determinism:

- ``compute_drift`` is a pure function of the two input records;
  no time, no random, no filesystem state.
- Input ordering does not affect output: the engine hashes every
  finding by id before classification. Two records with the same
  findings in different orders produce byte-identical DriftResults.
- Repeated calls return byte-identical output.

The classification uses a "risk" proxy on each finding:

    risk = debt_points * severity_weight
    severity_weight = {"info":1, "warning":2, "error":3, "critical":4}

A finding is ``WORSENED`` if the new risk is strictly greater than
the baseline risk (same id, same category/analyzer). It is
``IMPROVED`` if the new risk is strictly smaller. Same risk ==
``PERSISTENT``. This avoids false positives when a finding's
metadata changes but its debt impact is unchanged.
"""

from __future__ import annotations

from .drift_engine import (
    ALL_CLASSIFICATIONS,
    IMPROVED,
    NEW,
    PERSISTENT,
    RESOLVED,
    WORSENED,
    DriftCategoryBreakdown,
    DriftFinding,
    DriftResult,
    DriftSeverityBreakdown,
    DriftSummary,
    compute_drift,
)

__all__ = [
    "ALL_CLASSIFICATIONS",
    "IMPROVED",
    "NEW",
    "PERSISTENT",
    "RESOLVED",
    "WORSENED",
    "DriftCategoryBreakdown",
    "DriftFinding",
    "DriftResult",
    "DriftSeverityBreakdown",
    "DriftSummary",
    "compute_drift",
]
