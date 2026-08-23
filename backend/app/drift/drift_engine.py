"""Pure-function drift comparison between two ScanRecords.

See ``app.drift`` module docstring for the classification rules and
determinism contract.

Drill-down design
-----------------

The aggregate ``DriftSummary`` covers the headline numbers. The
``DriftResult`` exposes:

- ``by_category``: ``Dict[category, {new, resolved, persistent,
  worsened, improved, score_delta, debt_delta}]``
- ``by_analyzer``: same shape keyed on analyzer name
- ``by_severity``: same shape keyed on severity

All three drill-downs are deterministic and ordered by their keys
in insertion order — but the caller can sort if they need a stable
display order. The drift engine itself never reorders the inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.history.scan_record import FindingSnapshot, ScanRecord

# Severity -> numeric weight used by the risk proxy.
_SEVERITY_WEIGHT: dict[str, int] = {
    "info": 1,
    "warning": 2,
    "error": 3,
    "critical": 4,
}


# Public classification constants. Always compared as strings so
# the result JSON is stable.
NEW = "new"
RESOLVED = "resolved"
PERSISTENT = "persistent"
WORSENED = "worsened"
IMPROVED = "improved"

ALL_CLASSIFICATIONS: tuple[str, ...] = (
    NEW,
    RESOLVED,
    PERSISTENT,
    WORSENED,
    IMPROVED,
)


def _risk(snap: FindingSnapshot) -> float:
    """Numeric risk proxy used for WORSENED / IMPROVED classification."""
    sev_w = _SEVERITY_WEIGHT.get(snap.severity, 1)
    return float(snap.debt_points) * sev_w


@dataclass(frozen=True)
class DriftFinding:
    """A single finding's drift state, suitable for the API."""

    finding_id: str
    classification: str
    rule_id: str
    category: str
    analyzer: str
    severity: str
    confidence: float
    file_path: str
    line_start: int | None
    line_end: int | None
    symbol: str | None
    debt_points: int
    # Baseline fields (None for NEW).
    baseline_severity: str | None = None
    baseline_debt_points: int | None = None
    baseline_risk: float | None = None
    # Current fields (None for RESOLVED).
    current_severity: str | None = None
    current_debt_points: int | None = None
    current_risk: float | None = None
    message: str = ""
    suggestion: str | None = None
    # Risk delta for WORSENED / IMPROVED; 0 otherwise.
    risk_delta: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "classification": self.classification,
            "rule_id": self.rule_id,
            "category": self.category,
            "analyzer": self.analyzer,
            "severity": self.severity,
            "confidence": self.confidence,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "symbol": self.symbol,
            "debt_points": self.debt_points,
            "baseline_severity": self.baseline_severity,
            "baseline_debt_points": self.baseline_debt_points,
            "baseline_risk": self.baseline_risk,
            "current_severity": self.current_severity,
            "current_debt_points": self.current_debt_points,
            "current_risk": self.current_risk,
            "message": self.message,
            "suggestion": self.suggestion,
            "risk_delta": self.risk_delta,
        }


@dataclass
class _BucketCounts:
    """Counts and deltas for one bucket (category / analyzer / severity)."""

    new: int = 0
    resolved: int = 0
    persistent: int = 0
    worsened: int = 0
    improved: int = 0
    score_delta: float = 0.0
    debt_delta: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "new": self.new,
            "resolved": self.resolved,
            "persistent": self.persistent,
            "worsened": self.worsened,
            "improved": self.improved,
            "score_delta": self.score_delta,
            "debt_delta": self.debt_delta,
        }


DriftCategoryBreakdown = dict[str, _BucketCounts]
DriftSeverityBreakdown = dict[str, _BucketCounts]
AnalyzerBreakdown = dict[str, _BucketCounts]


@dataclass
class DriftSummary:
    score_delta: int = 0
    debt_delta: int = 0
    finding_delta: int = 0
    new_count: int = 0
    resolved_count: int = 0
    persistent_count: int = 0
    worsened_count: int = 0
    improved_count: int = 0
    baseline_scan_id: str = ""
    baseline_scanned_at: str = ""
    baseline_score: int = 0
    baseline_grade: str = ""
    baseline_total_debt_points: int = 0
    baseline_finding_count: int = 0
    current_scan_id: str = ""
    current_scanned_at: str = ""
    current_score: int = 0
    current_grade: str = ""
    current_total_debt_points: int = 0
    current_finding_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "score_delta": self.score_delta,
            "debt_delta": self.debt_delta,
            "finding_delta": self.finding_delta,
            "new_count": self.new_count,
            "resolved_count": self.resolved_count,
            "persistent_count": self.persistent_count,
            "worsened_count": self.worsened_count,
            "improved_count": self.improved_count,
            "baseline": {
                "scan_id": self.baseline_scan_id,
                "scanned_at": self.baseline_scanned_at,
                "score": self.baseline_score,
                "grade": self.baseline_grade,
                "total_debt_points": self.baseline_total_debt_points,
                "finding_count": self.baseline_finding_count,
            },
            "current": {
                "scan_id": self.current_scan_id,
                "scanned_at": self.current_scanned_at,
                "score": self.current_score,
                "grade": self.current_grade,
                "total_debt_points": self.current_total_debt_points,
                "finding_count": self.current_finding_count,
            },
        }


@dataclass
class DriftResult:
    summary: DriftSummary = field(default_factory=DriftSummary)
    findings: list[DriftFinding] = field(default_factory=list)
    by_category: DriftCategoryBreakdown = field(default_factory=dict)
    by_analyzer: AnalyzerBreakdown = field(default_factory=dict)
    by_severity: DriftSeverityBreakdown = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
            "by_category": {k: v.as_dict() for k, v in self.by_category.items()},
            "by_analyzer": {k: v.as_dict() for k, v in self.by_analyzer.items()},
            "by_severity": {k: v.as_dict() for k, v in self.by_severity.items()},
        }


# Empty baseline / empty current handling.
#
# If one side is empty, every finding on the other side is NEW or
# RESOLVED respectively; persistent/worsened/improved buckets stay
# empty. The drift result is still deterministic.


def _by_id(snapshots: list[FindingSnapshot]) -> dict[str, FindingSnapshot]:
    """Index findings by id. Duplicates keep the first occurrence.

    Duplicate finding IDs within a single scan are a separate
    problem (a different invariant); we don't crash on them, we
    just pick the first so the comparison is deterministic.
    """
    out: dict[str, FindingSnapshot] = {}
    for snap in snapshots:
        if snap.id not in out:
            out[snap.id] = snap
    return out


def _empty_buckets() -> tuple[
    DriftCategoryBreakdown, AnalyzerBreakdown, DriftSeverityBreakdown
]:
    return {}, {}, {}


def compute_drift(
    baseline: ScanRecord | None,
    current: ScanRecord | None,
) -> DriftResult:
    """Compare ``current`` to ``baseline`` and return a DriftResult.

    Either side may be None to represent "no prior scan" / "no
    findings now". The result is deterministic for fixed inputs.
    """
    summary = DriftSummary()
    findings: list[DriftFinding] = []
    by_category, by_analyzer, by_severity = _empty_buckets()

    # Header copy.
    if baseline is not None:
        summary.baseline_scan_id = baseline.scan_id
        summary.baseline_scanned_at = baseline.scanned_at
        summary.baseline_score = baseline.score
        summary.baseline_grade = baseline.grade
        summary.baseline_total_debt_points = baseline.total_debt_points
        summary.baseline_finding_count = baseline.finding_count
    if current is not None:
        summary.current_scan_id = current.scan_id
        summary.current_scanned_at = current.scanned_at
        summary.current_score = current.score
        summary.current_grade = current.grade
        summary.current_total_debt_points = current.total_debt_points
        summary.current_finding_count = current.finding_count

    summary.score_delta = summary.current_score - summary.baseline_score
    summary.debt_delta = (
        summary.current_total_debt_points - summary.baseline_total_debt_points
    )
    summary.finding_delta = (
        summary.current_finding_count - summary.baseline_finding_count
    )

    # Bucket keys seen across both sides (so a category with only
    # NEW findings still appears in by_category).
    baseline_by_id = _by_id(baseline.findings) if baseline else {}
    current_by_id = _by_id(current.findings) if current else {}

    # Union of categories / analyzers / severities for stable keys.
    all_categories: set[str] = set()
    all_analyzers: set[str] = set()
    all_severities: set[str] = set()
    if baseline is not None:
        for f in baseline.findings:
            all_categories.add(f.category)
            all_analyzers.add(f.analyzer)
            all_severities.add(f.severity)
    if current is not None:
        for f in current.findings:
            all_categories.add(f.category)
            all_analyzers.add(f.analyzer)
            all_severities.add(f.severity)

    for cat in all_categories:
        by_category.setdefault(cat, _BucketCounts())
    for az in all_analyzers:
        by_analyzer.setdefault(az, _BucketCounts())
    for sev in all_severities:
        by_severity.setdefault(sev, _BucketCounts())

    # Process findings. Iteration order is the union of ids, sorted
    # lexicographically, so the result is deterministic.
    all_ids = sorted(set(baseline_by_id.keys()) | set(current_by_id.keys()))

    for fid in all_ids:
        b = baseline_by_id.get(fid)
        c = current_by_id.get(fid)
        if b is None and c is not None:
            classification = NEW
            summary.new_count += 1
            finding_risk = _risk(c)
            _bump_bucket(by_category[c.category], classification, c, finding_risk)
            _bump_bucket(by_analyzer[c.analyzer], classification, c, finding_risk)
            _bump_bucket(by_severity[c.severity], classification, c, finding_risk)
            findings.append(_df_for_current(fid, c, finding_risk))
        elif c is None and b is not None:
            classification = RESOLVED
            summary.resolved_count += 1
            baseline_risk = _risk(b)
            _bump_bucket(by_category[b.category], classification, b, baseline_risk)
            _bump_bucket(by_analyzer[b.analyzer], classification, b, baseline_risk)
            _bump_bucket(by_severity[b.severity], classification, b, baseline_risk)
            findings.append(_df_for_baseline(fid, b, baseline_risk))
        elif b is not None and c is not None:
            b_risk = _risk(b)
            c_risk = _risk(c)
            if c_risk > b_risk:
                classification = WORSENED
                summary.worsened_count += 1
            elif c_risk < b_risk:
                classification = IMPROVED
                summary.improved_count += 1
            else:
                classification = PERSISTENT
                summary.persistent_count += 1
            _bump_bucket_pair(
                by_category[c.category],
                classification,
                b,
                c,
                b_risk,
                c_risk,
            )
            _bump_bucket_pair(
                by_analyzer[c.analyzer],
                classification,
                b,
                c,
                b_risk,
                c_risk,
            )
            _bump_bucket_pair(
                by_severity[c.severity],
                classification,
                b,
                c,
                b_risk,
                c_risk,
            )
            findings.append(_df_for_pair(fid, b, c, b_risk, c_risk, classification))

    # Final findings list is sorted by (classification, finding_id)
    # for deterministic output ordering across re-runs.
    findings.sort(
        key=lambda d: (
            # Classification priority: NEW first, RESOLVED, WORSENED,
            # IMPROVED, PERSISTENT. Tie-break on finding_id.
            _CLASSIFICATION_ORDER[d.classification],
            d.finding_id,
        )
    )

    return DriftResult(
        summary=summary,
        findings=findings,
        by_category=by_category,
        by_analyzer=by_analyzer,
        by_severity=by_severity,
    )


_CLASSIFICATION_ORDER: dict[str, int] = {
    NEW: 0,
    RESOLVED: 1,
    WORSENED: 2,
    IMPROVED: 3,
    PERSISTENT: 4,
}


def _bump_bucket(
    bucket: _BucketCounts,
    classification: str,
    snap: FindingSnapshot,
    risk: float,
) -> None:
    """Increment a bucket for a single-sided (NEW or RESOLVED) finding."""
    if classification == NEW:
        bucket.new += 1
        bucket.debt_delta += snap.debt_points
    elif classification == RESOLVED:
        bucket.resolved += 1
        bucket.debt_delta -= snap.debt_points
    # Persistent / worsened / improved are not single-sided.


def _bump_bucket_pair(
    bucket: _BucketCounts,
    classification: str,
    baseline: FindingSnapshot,
    current: FindingSnapshot,
    baseline_risk: float,
    current_risk: float,
) -> None:
    """Increment a bucket for a paired (PERSISTENT/WORSENED/IMPROVED) finding."""
    if classification == PERSISTENT:
        bucket.persistent += 1
    elif classification == WORSENED:
        bucket.worsened += 1
        bucket.debt_delta += current.debt_points - baseline.debt_points
    elif classification == IMPROVED:
        bucket.improved += 1
        bucket.debt_delta += current.debt_points - baseline.debt_points


def _df_for_current(
    fid: str, snap: FindingSnapshot, risk: float
) -> DriftFinding:
    return DriftFinding(
        finding_id=fid,
        classification=NEW,
        rule_id=snap.rule_id,
        category=snap.category,
        analyzer=snap.analyzer,
        severity=snap.severity,
        confidence=snap.confidence,
        file_path=snap.file_path,
        line_start=snap.line_start,
        line_end=snap.line_end,
        symbol=snap.symbol,
        debt_points=snap.debt_points,
        baseline_severity=None,
        baseline_debt_points=None,
        baseline_risk=None,
        current_severity=snap.severity,
        current_debt_points=snap.debt_points,
        current_risk=risk,
        message=snap.message,
        suggestion=snap.suggestion,
        risk_delta=0.0,
    )


def _df_for_baseline(
    fid: str, snap: FindingSnapshot, risk: float
) -> DriftFinding:
    return DriftFinding(
        finding_id=fid,
        classification=RESOLVED,
        rule_id=snap.rule_id,
        category=snap.category,
        analyzer=snap.analyzer,
        severity=snap.severity,
        confidence=snap.confidence,
        file_path=snap.file_path,
        line_start=snap.line_start,
        line_end=snap.line_end,
        symbol=snap.symbol,
        debt_points=0,
        baseline_severity=snap.severity,
        baseline_debt_points=snap.debt_points,
        baseline_risk=risk,
        current_severity=None,
        current_debt_points=None,
        current_risk=None,
        message=snap.message,
        suggestion=snap.suggestion,
        risk_delta=0.0,
    )


def _df_for_pair(
    fid: str,
    baseline: FindingSnapshot,
    current: FindingSnapshot,
    baseline_risk: float,
    current_risk: float,
    classification: str,
) -> DriftFinding:
    return DriftFinding(
        finding_id=fid,
        classification=classification,
        rule_id=current.rule_id,
        category=current.category,
        analyzer=current.analyzer,
        severity=current.severity,
        confidence=current.confidence,
        file_path=current.file_path,
        line_start=current.line_start,
        line_end=current.line_end,
        symbol=current.symbol,
        debt_points=current.debt_points,
        baseline_severity=baseline.severity,
        baseline_debt_points=baseline.debt_points,
        baseline_risk=baseline_risk,
        current_severity=current.severity,
        current_debt_points=current.debt_points,
        current_risk=current_risk,
        message=current.message,
        suggestion=current.suggestion,
        risk_delta=current_risk - baseline_risk,
    )
