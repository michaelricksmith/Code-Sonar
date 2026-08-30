"""Deterministic feature extraction from persisted scan records."""

from __future__ import annotations

from app.history.scan_record import ScanRecord
from app.ml.features.schema import ScanFeatureVector


def _count(mapping: dict[str, int], key: str) -> float:
    return float(mapping.get(key, 0))


def extract_scan_features(record: ScanRecord) -> ScanFeatureVector:
    """Convert a ``ScanRecord`` into the v1.0 ML feature vector.

    This function is pure: it does not read time, random state, the filesystem,
    Git, model artifacts, or network services. Therefore the same persisted scan
    record always produces the same vector.
    """
    finding_count = len(record.findings)
    if finding_count:
        mean_confidence = sum(float(f.confidence) for f in record.findings) / finding_count
        mean_debt_points = sum(float(f.debt_points) for f in record.findings) / finding_count
        max_finding_risk = max(float(f.risk) for f in record.findings)
        analyzer_diversity = float(len({f.analyzer for f in record.findings}))
    else:
        mean_confidence = 0.0
        mean_debt_points = 0.0
        max_finding_risk = 0.0
        analyzer_diversity = 0.0

    return ScanFeatureVector(
        score=float(record.score),
        total_debt_points=float(record.total_debt_points),
        finding_count=float(record.finding_count),
        severity_info=_count(record.severity_distribution, "info"),
        severity_warning=_count(record.severity_distribution, "warning"),
        severity_error=_count(record.severity_distribution, "error"),
        severity_critical=_count(record.severity_distribution, "critical"),
        category_complexity=_count(record.findings_by_category, "complexity"),
        category_staleness=_count(record.findings_by_category, "staleness"),
        category_security=_count(record.findings_by_category, "security"),
        category_duplication=_count(record.findings_by_category, "duplication"),
        category_testing=_count(record.findings_by_category, "testing"),
        category_maintainability=_count(record.findings_by_category, "maintainability"),
        source_findings=_count(record.findings_source_breakdown, "source"),
        test_findings=_count(record.findings_source_breakdown, "test"),
        fixture_findings=_count(record.findings_source_breakdown, "fixture"),
        mean_confidence=mean_confidence,
        mean_debt_points=mean_debt_points,
        max_finding_risk=max_finding_risk,
        analyzer_diversity=analyzer_diversity,
    )
