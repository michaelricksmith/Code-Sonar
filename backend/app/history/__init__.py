"""Scan-history layer for Code Sonar (Checkpoint 6, Lane 1).

Provides a deterministic persistence layer for completed scans and a
pure drift-comparison engine. The history layer is intentionally
small: each scan record carries its full findings snapshot plus a
flat aggregate summary, so the drift engine can compare any two
records without re-running analyzers.

Design constraints:

- **Local persistence only** — no external DB. The default
  implementation is a single JSONL file in the user's data dir.
- **Pluggable storage** — ``HistoryStore`` is an abstract base; the
  JSONL implementation is the reference. Tests use an in-memory
  implementation.
- **Repository identity is stable and deterministic** — derived from
  the resolved absolute path of the repository root (lower-cased,
  forward-slash normalized). No env, no hostname, no timestamp.
- **Finding-ID is the comparison key** — drift is computed by
  joining on ``finding.id``.
- **Schema is versioned** — every record carries ``schema_version``;
  the loader refuses to read records with an unknown future
  version. This guards against silent corruption when a future
  release changes the snapshot shape.
- **No secrets in persisted records** — evidence fields are
  redacted via ``app.security.redact_secrets`` before persistence,
  so a historical snapshot cannot leak a credential even if a
  future analyzer regresses.
"""

from __future__ import annotations

from .history_store import HistoryStore, InMemoryHistoryStore, JsonlHistoryStore
from .repository_identity import compute_repository_id, display_name
from .scan_record import (
    SCHEMA_VERSION,
    FindingSnapshot,
    ScanRecord,
    build_scan_record,
)

__all__ = [
    "SCHEMA_VERSION",
    "FindingSnapshot",
    "HistoryStore",
    "InMemoryHistoryStore",
    "JsonlHistoryStore",
    "ScanRecord",
    "build_scan_record",
    "compute_repository_id",
    "display_name",
]
