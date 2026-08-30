"""ML-1 invariants for deterministic scan-level feature extraction."""

from app.history import build_scan_record
from app.ml.features import FEATURE_SCHEMA_VERSION, ScanFeatureVector, extract_scan_features
from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.scoring.engine import calculate_score


def _finding(
    *,
    finding_id: str,
    category: FindingCategory,
    severity: FindingSeverity,
    confidence: float,
    debt_points: int,
    analyzer: str,
    file_path: str,
) -> Finding:
    return Finding(
        id=finding_id,
        rule_id=f"{analyzer}:rule",
        category=category,
        severity=severity,
        confidence=confidence,
        file_path=file_path,
        line_start=1,
        line_end=1,
        symbol=None,
        evidence="safe evidence",
        message="test finding",
        suggestion="fix it",
        debt_points=debt_points,
        remediation_effort="1 hour",
        analyzer=analyzer,
        metadata={},
    )


def _record():
    findings = [
        _finding(
            finding_id="f1",
            category=FindingCategory.COMPLEXITY,
            severity=FindingSeverity.WARNING,
            confidence=0.8,
            debt_points=5,
            analyzer="cyclomatic_complexity",
            file_path="src/a.py",
        ),
        _finding(
            finding_id="f2",
            category=FindingCategory.SECURITY,
            severity=FindingSeverity.CRITICAL,
            confidence=1.0,
            debt_points=10,
            analyzer="secrets",
            file_path="tests/test_a.py",
        ),
    ]
    scoring = calculate_score(findings)
    return build_scan_record(
        repository_id="repo-1",
        repository_path="repo",
        findings=findings,
        scoring=scoring,
        scan_id="scan-1",
        scanned_at="2026-08-30T12:00:00+00:00",
    )


def test_feature_schema_v1_has_stable_order() -> None:
    assert FEATURE_SCHEMA_VERSION == "1.0"
    assert ScanFeatureVector.feature_names() == (
        "score",
        "total_debt_points",
        "finding_count",
        "severity_info",
        "severity_warning",
        "severity_error",
        "severity_critical",
        "category_complexity",
        "category_staleness",
        "category_security",
        "category_duplication",
        "category_testing",
        "category_maintainability",
        "source_findings",
        "test_findings",
        "fixture_findings",
        "mean_confidence",
        "mean_debt_points",
        "max_finding_risk",
        "analyzer_diversity",
    )


def test_same_scan_produces_identical_feature_payload() -> None:
    record = _record()
    first = extract_scan_features(record).to_dict()
    second = extract_scan_features(record).to_dict()
    assert first == second


def test_feature_values_capture_scan_aggregates() -> None:
    vector = extract_scan_features(_record())

    assert vector.finding_count == 2.0
    assert vector.total_debt_points == 15.0
    assert vector.severity_warning == 1.0
    assert vector.severity_critical == 1.0
    assert vector.category_complexity == 1.0
    assert vector.category_security == 1.0
    assert vector.source_findings == 1.0
    assert vector.test_findings == 1.0
    assert vector.fixture_findings == 0.0
    assert vector.mean_confidence == 0.9
    assert vector.mean_debt_points == 7.5
    assert vector.max_finding_risk == 40.0
    assert vector.analyzer_diversity == 2.0


def test_serialized_payload_exposes_schema_version() -> None:
    payload = extract_scan_features(_record()).to_dict()

    assert payload["feature_schema_version"] == "1.0"
    assert list(payload["features"].keys()) == list(ScanFeatureVector.feature_names())
