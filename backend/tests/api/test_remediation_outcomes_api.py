"""API tests for recording observed remediation outcomes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ml.outcomes import JsonlOutcomeStore
from app.ml.outcomes.runtime import set_outcome_store


@pytest.fixture(autouse=True)
def reset_store() -> None:
    set_outcome_store(None)
    yield
    set_outcome_store(None)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    set_outcome_store(JsonlOutcomeStore(tmp_path / "outcomes.jsonl"))
    return TestClient(app)


def _payload() -> dict[str, object]:
    return {
        "outcome_id": "outcome-1",
        "repository_id": "repo-1",
        "finding_id": "finding-1",
        "before_scan_id": "scan-before",
        "after_scan_id": "scan-after",
        "attempted_at": "2026-08-30T20:30:00+00:00",
        "executor": "cursor",
        "remediation_kind": "automated_patch",
        "build_passed": True,
        "tests_passed": True,
        "finding_resolved": True,
        "finding_reintroduced": False,
        "regression_detected": False,
        "score_delta": 18,
        "debt_points_delta": -12,
    }


def test_record_outcome_returns_high_trust_label_without_execution(client: TestClient) -> None:
    response = client.post("/api/ml/remediation-outcomes", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"]["successful"] is True
    assert data["training_label"]["task"] == "remediation_success"
    assert data["training_label"]["value"] == "1"
    assert data["training_label"]["trust_tier"] == "remediation_outcome"
    assert data["training_label"]["is_proxy"] is False
    assert data["deterministic_score_unchanged"] is True
    assert data["execution_performed"] is False


def test_duplicate_outcome_is_rejected(client: TestClient) -> None:
    assert client.post("/api/ml/remediation-outcomes", json=_payload()).status_code == 200

    response = client.post("/api/ml/remediation-outcomes", json=_payload())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "remediation_outcome_exists"


def test_recorded_outcome_can_be_read_back(client: TestClient) -> None:
    client.post("/api/ml/remediation-outcomes", json=_payload())

    response = client.get("/api/ml/remediation-outcomes/outcome-1")

    assert response.status_code == 200
    assert response.json()["score_delta"] == 18
    assert response.json()["debt_points_delta"] == -12


def test_missing_outcome_returns_404(client: TestClient) -> None:
    response = client.get("/api/ml/remediation-outcomes/missing")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "remediation_outcome_not_found"
