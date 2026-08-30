"""Tests for read-only Code Sonar ML metadata endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ml.evaluation import BinaryClassificationMetrics, ModelRecord, ModelRegistry
from app.ml.runtime import set_model_registry


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    set_model_registry(ModelRegistry())
    yield
    set_model_registry(ModelRegistry())


def _metrics(f1: float, roc_auc: float) -> BinaryClassificationMetrics:
    return BinaryClassificationMetrics(
        accuracy=0.8,
        precision=0.75,
        recall=0.85,
        f1=f1,
        roc_auc=roc_auc,
        true_negative=8,
        false_positive=2,
        false_negative=1,
        true_positive=9,
    )


def test_models_endpoint_is_empty_by_default(client: TestClient) -> None:
    response = client.get("/api/ml/models")
    assert response.status_code == 200
    assert response.json() == {"count": 0, "task": None, "models": []}


def test_models_endpoint_lists_and_filters_metadata(client: TestClient) -> None:
    registry = ModelRegistry(
        [
            ModelRecord(
                task="debt_risk",
                model_name="logistic_debt_risk",
                model_version="0.1.0",
                metrics=_metrics(0.82, 0.90),
                dataset_version="dataset-v1",
                trained_at="2026-08-30T19:00:00+00:00",
                artifact_ref="models/logistic-v1",
                is_champion=True,
            ),
            ModelRecord(
                task="remediation_success",
                model_name="decision_tree_remediation",
                model_version="0.1.0",
                metrics=_metrics(0.76, 0.84),
            ),
        ]
    )
    set_model_registry(registry)

    response = client.get("/api/ml/models?task=debt_risk")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["task"] == "debt_risk"
    assert payload["models"][0]["model_name"] == "logistic_debt_risk"
    assert payload["models"][0]["dataset_version"] == "dataset-v1"
    assert payload["models"][0]["artifact_ref"] == "models/logistic-v1"


def test_model_performance_returns_champion_and_metrics(client: TestClient) -> None:
    registry = ModelRegistry(
        [
            ModelRecord(
                task="debt_risk",
                model_name="logistic_debt_risk",
                model_version="0.1.0",
                metrics=_metrics(0.82, 0.90),
                is_champion=True,
            ),
            ModelRecord(
                task="debt_risk",
                model_name="svm_debt_risk",
                model_version="0.1.0",
                metrics=_metrics(0.80, 0.92),
            ),
        ]
    )
    set_model_registry(registry)

    response = client.get("/api/ml/model-performance?task=debt_risk")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert len(payload["champions"]) == 1
    assert payload["champions"][0]["model_name"] == "logistic_debt_risk"
    assert payload["champions"][0]["metrics"]["f1"] == pytest.approx(0.82)
    assert payload["models"][1]["model_name"] == "svm_debt_risk"


def test_read_endpoints_do_not_mutate_registry(client: TestClient) -> None:
    record = ModelRecord(
        task="debt_risk",
        model_name="logistic_debt_risk",
        model_version="0.1.0",
        metrics=_metrics(0.82, 0.90),
    )
    registry = ModelRegistry([record])
    set_model_registry(registry)

    before = registry.all_records()
    assert client.get("/api/ml/models").status_code == 200
    assert client.get("/api/ml/model-performance").status_code == 200
    assert registry.all_records() == before
