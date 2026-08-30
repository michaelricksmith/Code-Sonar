"""Tests for controlled ML prediction runtime and API behavior."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ml.features import ScanFeatureVector
from app.ml.runtime import (
    clear_prediction_models,
    register_prediction_model,
    set_feature_provider,
)


@pytest.fixture(autouse=True)
def reset_prediction_runtime():
    clear_prediction_models()
    set_feature_provider(None)
    yield
    clear_prediction_models()
    set_feature_provider(None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def sample_features() -> ScanFeatureVector:
    return ScanFeatureVector(
        score=700.0,
        total_debt_points=120.0,
        finding_count=8.0,
        severity_info=1.0,
        severity_warning=4.0,
        severity_error=2.0,
        severity_critical=1.0,
        category_complexity=2.0,
        category_staleness=1.0,
        category_security=2.0,
        category_duplication=1.0,
        category_testing=1.0,
        category_maintainability=1.0,
        source_findings=7.0,
        test_findings=1.0,
        fixture_findings=0.0,
        mean_confidence=0.88,
        mean_debt_points=15.0,
        max_finding_risk=0.95,
        analyzer_diversity=5.0,
    )


@dataclass(frozen=True)
class FakePrediction:
    model_name: str = "fake_debt_risk"
    model_version: str = "test-1"

    def to_dict(self) -> dict[str, object]:
        return {
            "predicted_class": 1,
            "probability": 0.82,
            "confidence": 0.82,
            "model_name": self.model_name,
            "model_version": self.model_version,
        }


class FakeModel:
    model_name = "fake_debt_risk"
    model_version = "test-1"

    def predict(self, features: ScanFeatureVector) -> FakePrediction:
        assert features.score == 700.0
        return FakePrediction()


class NotReadyModel:
    model_name = "not_ready"
    model_version = "test-1"

    def predict(self, features: ScanFeatureVector) -> FakePrediction:
        raise RuntimeError("Model must be fitted before prediction")


def test_predict_returns_503_when_model_unavailable(client: TestClient) -> None:
    response = client.post(
        "/api/ml/predict",
        json={"scan_id": "scan-1", "task": "debt_risk"},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "ml_model_unavailable"
    assert detail["task"] == "debt_risk"


def test_predict_returns_404_when_scan_features_missing(client: TestClient) -> None:
    register_prediction_model("debt_risk", FakeModel())
    set_feature_provider(lambda scan_id: None)

    response = client.post(
        "/api/ml/predict",
        json={"scan_id": "missing-scan", "task": "debt_risk"},
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "scan_features_not_found"
    assert detail["scan_id"] == "missing-scan"


def test_predict_uses_stored_scan_features_and_is_advisory(client: TestClient) -> None:
    register_prediction_model("debt_risk", FakeModel())
    set_feature_provider(lambda scan_id: sample_features() if scan_id == "scan-1" else None)

    response = client.post(
        "/api/ml/predict",
        json={"scan_id": "scan-1", "task": "debt_risk"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["scan_id"] == "scan-1"
    assert data["task"] == "debt_risk"
    assert data["advisory_only"] is True
    assert data["deterministic_score_unchanged"] is True
    assert data["prediction"]["probability"] == 0.82
    assert data["prediction"]["model_name"] == "fake_debt_risk"


def test_predict_returns_503_for_loaded_but_unready_model(client: TestClient) -> None:
    register_prediction_model("debt_risk", NotReadyModel())
    set_feature_provider(lambda scan_id: sample_features())

    response = client.post(
        "/api/ml/predict",
        json={"scan_id": "scan-1", "task": "debt_risk"},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "ml_model_not_ready"
