"""ScanRecord — a snapshot of one scan's results.

The record is intentionally flat and self-contained: any consumer
(drift engine, history API, dashboard) can reconstruct the scan's
shape from a single record without re-running analyzers.

Schema versioning
-----------------

``SCHEMA_VERSION`` is a string. When the snapshot shape changes,
bump it. The ``JsonlHistoryStore`` loader refuses records whose
``schema_version`` is unknown to the running code, which guards
against silent corruption when a future release reads an old
record and mis-interprets a renamed field.

Evidence redaction
------------------

``build_scan_record`` calls ``app.security.redact_secrets`` on every
finding's ``evidence`` field before persistence. This is a defense
in depth: even if a future analyzer regresses and emits raw
credentials in evidence, the historical record will not store
them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.finding import Finding
from app.scoring.engine import SCORING_VERSION, ScoringResult
from app.security import redact_secrets

SCHEMA_VERSION: str = "1.0"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FindingSnapshot:
    """A redacted, persisted view of a Finding.

    Field subset chosen for drift comparison + dashboard re-display.
    The full ``metadata`` dict is preserved so the dashboard can
    show the same payload as the live scan.
    """

    __slots__ = (
        "id",
        "rule_id",
        "category",
        "severity",
        "confidence",
        "file_path",
        "line_start",
        "line_end",
        "symbol",
        "evidence",
        "message",
        "suggestion",
        "debt_points",
        "analyzer",
        "metadata",
    )

    def __init__(self, finding: Finding) -> None:
        self.id: str = finding.id
        self.rule_id: str = finding.rule_id
        self.category: str = finding.category.value
        self.severity: str = finding.severity.value
        self.confidence: float = finding.confidence
        self.file_path: str = finding.file_path
        self.line_start: int | None = finding.line_start
        self.line_end: int | None = finding.line_end
        self.symbol: str | None = finding.symbol
        # Redact secrets on the way in — historical storage cannot
        # leak a credential even if a future analyzer regresses.
        self.evidence: str = redact_secrets(finding.evidence or "") or ""
        self.message: str = finding.message
        self.suggestion: str | None = finding.suggestion
        self.debt_points: int = finding.debt_points
        self.analyzer: str = finding.analyzer
        self.metadata: dict[str, Any] = dict(finding.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "symbol": self.symbol,
            # Defense in depth: redact on the way out. Any caller
            # that builds a snapshot from arbitrary input (tests,
            # future analyzers, migrated records) still gets a
            # safe persisted form.
            "evidence": redact_secrets(self.evidence or "") or "",
            "message": self.message,
            "suggestion": self.suggestion,
            "debt_points": self.debt_points,
            "analyzer": self.analyzer,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FindingSnapshot":
        snap = cls.__new__(cls)
        snap.id = data["id"]
        snap.rule_id = data["rule_id"]
        snap.category = data["category"]
        snap.severity = data["severity"]
        snap.confidence = float(data["confidence"])
        snap.file_path = data["file_path"]
        snap.line_start = data.get("line_start")
        snap.line_end = data.get("line_end")
        snap.symbol = data.get("symbol")
        snap.evidence = data.get("evidence", "")
        snap.message = data.get("message", "")
        snap.suggestion = data.get("suggestion")
        snap.debt_points = int(data["debt_points"])
        snap.analyzer = data["analyzer"]
        snap.metadata = dict(data.get("metadata") or {})
        return snap

    def matches_id(self, other_id: str) -> bool:
        return self.id == other_id

    @property
    def risk(self) -> float:
        """Numeric risk proxy used for WORSENED / IMPROVED classification.

        Higher debt points and higher severity weigh more. Severity
        ordering: info=1, warning=2, error=3, critical=4.
        """
        sev_w = {"info": 1, "warning": 2, "error": 3, "critical": 4}.get(
            self.severity, 1
        )
        return float(self.debt_points) * sev_w


class ScanRecord:
    """A persisted snapshot of one scan's results.

    Two records of the same repository with the same ``id`` are
    guaranteed equal-by-value.
    """

    __slots__ = (
        "scan_id",
        "repository_id",
        "repository_path",
        "scanned_at",
        "schema_version",
        "scoring_version",
        "score",
        "grade",
        "total_debt_points",
        "finding_count",
        "category_scores",
        "severity_distribution",
        "findings_by_category",
        "findings_source_breakdown",
        "findings",
    )

    def __init__(
        self,
        scan_id: str,
        repository_id: str,
        repository_path: str,
        scanned_at: str,
        schema_version: str,
        score: int,
        grade: str,
        total_debt_points: int,
        finding_count: int,
        category_scores: dict[str, int],
        severity_distribution: dict[str, int],
        findings_by_category: dict[str, int],
        findings_source_breakdown: dict[str, int],
        findings: list[FindingSnapshot],
        scoring_version: str = "legacy-unversioned",
    ) -> None:
        self.scan_id = scan_id
        self.repository_id = repository_id
        self.repository_path = repository_path
        self.scanned_at = scanned_at
        self.schema_version = schema_version
        self.scoring_version = scoring_version
        self.score = score
        self.grade = grade
        self.total_debt_points = total_debt_points
        self.finding_count = finding_count
        self.category_scores = dict(category_scores)
        self.severity_distribution = dict(severity_distribution)
        self.findings_by_category = dict(findings_by_category)
        self.findings_source_breakdown = dict(findings_source_breakdown)
        self.findings = list(findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "repository_id": self.repository_id,
            "repository_path": self.repository_path,
            "scanned_at": self.scanned_at,
            "schema_version": self.schema_version,
            "scoring_version": self.scoring_version,
            "score": self.score,
            "grade": self.grade,
            "total_debt_points": self.total_debt_points,
            "finding_count": self.finding_count,
            "category_scores": dict(self.category_scores),
            "severity_distribution": dict(self.severity_distribution),
            "findings_by_category": dict(self.findings_by_category),
            "findings_source_breakdown": dict(self.findings_source_breakdown),
            "findings": [f.to_dict() for f in self.findings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScanRecord":
        record = cls.__new__(cls)
        record.scan_id = data["scan_id"]
        record.repository_id = data["repository_id"]
        record.repository_path = data["repository_path"]
        record.scanned_at = data["scanned_at"]
        record.schema_version = data["schema_version"]
        # Records written before scoring-version tracking remain readable.
        record.scoring_version = data.get("scoring_version", "legacy-unversioned")
        record.score = int(data["score"])
        record.grade = data["grade"]
        record.total_debt_points = int(data["total_debt_points"])
        record.finding_count = int(data["finding_count"])
        record.category_scores = dict(data.get("category_scores") or {})
        record.severity_distribution = dict(data.get("severity_distribution") or {})
        record.findings_by_category = dict(data.get("findings_by_category") or {})
        record.findings_source_breakdown = dict(
            data.get("findings_source_breakdown") or {}
        )
        record.findings = [
            FindingSnapshot.from_dict(f) for f in data.get("findings") or []
        ]
        return record


def build_scan_record(
    repository_id: str,
    repository_path: str,
    findings: list[Finding],
    scoring: ScoringResult,
    *,
    scan_id: str | None = None,
    scanned_at: str | None = None,
) -> ScanRecord:
    """Build a ``ScanRecord`` from a finished scan.

    The ``scan_id`` defaults to a UUID4 hex string when not provided.
    Callers that want a deterministic id (e.g. test fixtures) must
    pass it explicitly.
    """
    return ScanRecord(
        scan_id=scan_id or uuid.uuid4().hex,
        repository_id=repository_id,
        repository_path=repository_path,
        scanned_at=scanned_at or _utcnow_iso(),
        schema_version=SCHEMA_VERSION,
        scoring_version=SCORING_VERSION,
        score=scoring.score,
        grade=scoring.grade,
        total_debt_points=scoring.total_debt_points,
        finding_count=scoring.finding_count,
        category_scores=dict(scoring.category_scores),
        severity_distribution=dict(scoring.severity_distribution),
        findings_by_category=dict(scoring.findings_by_category),
        findings_source_breakdown=dict(scoring.findings_source_breakdown),
        findings=[FindingSnapshot(f) for f in findings],
    )
