"""API tests for ML-6 historical similarity retrieval."""

from fastapi.testclient import TestClient

from app.main import app
from app.ml.datasets import DatasetRow, LabelProvenance, LabelTrustTier
from app.ml.features import ScanFeatureVector
from app.ml.runtime import (
    clear_similarity_indexes,
    register_similarity_index,
    set_feature_provider,
)
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


def setup_function() -> None:
    clear_similarity_indexes()
    set_feature_provider(None)


def teardown_function() -> None:
    clear_similarity_indexes()
    set_feature_provider(None)


def test_similar_scans_returns_503_when_index_unavailable() -> None:
    response = TestClient(app).get("/api/ml/similar-scans/scan-1")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "similarity_index_unavailable"


def test_similar_scans_returns_404_when_scan_features_missing() -> None:
    index = SimilarityIndex()
    index.fit([_row(1, 0.1, 0), _row(2, 0.8, 1)])
    register_similarity_index("debt_risk", index)
    set_feature_provider(lambda scan_id: None)

    response = TestClient(app).get("/api/ml/similar-scans/missing")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "scan_features_not_found"


def test_similar_scans_returns_historical_neighbors_without_self() -> None:
    rows = [_row(1, 0.1, 0), _row(2, 0.2, 0), _row(3, 0.8, 1)]
    index = SimilarityIndex()
    index.fit(rows)
    register_similarity_index("debt_risk", index)
    set_feature_provider(lambda scan_id: _features(0.1) if scan_id == "scan-1" else None)

    response = TestClient(app).get("/api/ml/similar-scans/scan-1?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["advisory_only"] is True
    assert payload["deterministic_score_unchanged"] is True
    assert [case["scan_id"] for case in payload["similar_scans"]] == ["scan-2", "scan-3"]
    assert payload["similar_scans"][0]["label_trust_tier"] == "proxy"
