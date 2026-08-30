"""ML-6 historical similarity invariants."""

import pytest

from app.ml.datasets import DatasetRow, LabelProvenance, LabelTrustTier
from app.ml.features import ScanFeatureVector
from app.ml.similarity import SimilarityIndex


def _features(signal: float) -> ScanFeatureVector:
    return ScanFeatureVector(
        score=850.0 - signal * 100.0,
        total_debt_points=signal * 20.0,
        finding_count=signal * 5.0,
        severity_info=0.0,
        severity_warning=signal,
        severity_error=signal,
        severity_critical=signal,
        category_complexity=signal,
        category_staleness=0.0,
        category_security=signal,
        category_duplication=0.0,
        category_testing=signal,
        category_maintainability=signal,
        source_findings=signal * 3.0,
        test_findings=0.0,
        fixture_findings=0.0,
        mean_confidence=0.9,
        mean_debt_points=signal * 4.0,
        max_finding_risk=signal * 10.0,
        analyzer_diversity=max(1.0, signal * 2.0),
    )


def _row(index: int, signal: float, label: int) -> DatasetRow:
    return DatasetRow(
        row_id=f"row-{index}",
        repository_group=f"repo-{index}",
        lineage_id=f"repo-{index}",
        scan_id=f"scan-{index}",
        features=_features(signal),
        label=LabelProvenance(
            task="debt_risk",
            value=str(label),
            trust_tier=LabelTrustTier.PROXY,
            source="unit-test",
        ),
    )


def test_similarity_index_returns_nearest_cases_and_excludes_query_scan() -> None:
    rows = [_row(1, 0.1, 0), _row(2, 0.2, 0), _row(3, 0.8, 1)]
    index = SimilarityIndex()
    index.fit(rows)

    cases = index.query(_features(0.1), limit=2, exclude_scan_id="scan-1")

    assert [case.scan_id for case in cases] == ["scan-2", "scan-3"]
    assert cases[0].distance <= cases[1].distance
    assert cases[0].label_value == "0"
    assert cases[0].label_trust_tier == "proxy"


def test_similarity_index_requires_fit() -> None:
    with pytest.raises(RuntimeError, match="must be fitted"):
        SimilarityIndex().query(_features(0.2))


def test_similarity_index_rejects_empty_training_set() -> None:
    with pytest.raises(ValueError, match="At least one"):
        SimilarityIndex().fit([])
