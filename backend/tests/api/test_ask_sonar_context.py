"""API tests for Ask Sonar grounding context."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ask_sonar.runtime import set_scan_provider
from app.history import ScanRecord
from app.main import app
from app.ml.runtime import clear_prediction_models, clear_similarity_indexes


@pytest.fixture(autouse=True)
def reset_runtime():
    set_scan_provider(None)
    clear_prediction_models()
    clear_similarity_indexes()
    yield
    set_scan_provider(None)
    clear_prediction_models()
    clear_similarity_indexes()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _record() -> ScanRecord:
    return ScanRecord(
        scan_id="scan-1",
        repository_id="repo-1",
        repository_path="example/repo",
        scanned_at="2026-08-30T20:00:00+00:00",
        schema_version="1.0",
        score=720,
        grade="B",
        total_debt_points=30,
        finding_count=0,
        category_scores={"maintainability": 700},
        severity_distribution={},
        findings_by_category={},
        findings_source_breakdown={"source": 0, "test": 0, "fixture": 0},
        findings=[],
    )


def test_context_returns_404_for_unknown_scan(client: TestClient) -> None:
    set_scan_provider(lambda scan_id: None)

    response = client.get("/api/ask-sonar/context/missing")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "ask_sonar_scan_not_found"
    assert detail["scan_id"] == "missing"


def test_context_returns_authoritative_scan_facts_without_ml(client: TestClient) -> None:
    record = _record()
    set_scan_provider(lambda scan_id: record if scan_id == "scan-1" else None)

    response = client.get("/api/ask-sonar/context/scan-1")

    assert response.status_code == 200
    data = response.json()
    assert data["context_schema_version"] == "1.0"
    assert data["deterministic_score_unchanged"] is True
    assert data["source_policy"]["deterministic_is_authoritative"] is True
    assert data["deterministic"]["score"] == 720
    assert data["deterministic"]["grade"] == "B"
    assert data["ml_prediction"]["status"] == "unavailable"
    assert data["historical_similarity"]["status"] == "unavailable"
