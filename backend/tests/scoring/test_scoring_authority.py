"""Authority gates and version provenance for deterministic scoring."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.history import InMemoryHistoryStore, ScanRecord
from app.main import app, get_history_store, set_history_store
from app.scoring.engine import SCORING_VERSION
from app.services import repository as repository_service
from app.services.repository import AnalyzerExecutionStatus, ScanExecutionResult


class _FailingAnalyzer:
    name = "broken"

    def analyze(self, _repo_path):
        raise RuntimeError("deliberate test failure")


def test_repository_execution_reports_analyzer_failure(tmp_path) -> None:
    with patch(
        "app.services.repository.get_registered_analyzers",
        return_value=[_FailingAnalyzer()],
    ):
        execution = repository_service.scan_repository(tmp_path)
    assert execution.complete is False
    assert execution.findings == ()
    assert execution.analyzers == (
        AnalyzerExecutionStatus("broken", "failed", 0, "RuntimeError"),
    )


def test_empty_analyzer_registry_is_not_authoritative() -> None:
    execution = ScanExecutionResult(findings=(), analyzers=())
    assert execution.complete is False


def test_analyzer_failure_prevents_authoritative_score(test_repo_fixture) -> None:
    incomplete = ScanExecutionResult(
        findings=(),
        analyzers=(AnalyzerExecutionStatus("broken", "failed", 0, "RuntimeError"),),
    )
    with patch("app.main.scan_repository", return_value=incomplete):
        response = TestClient(app).post("/api/scan", json={"repo_path": str(test_repo_fixture)})
    assert response.status_code == 503
    assert "score" not in response.json()
    assert response.json()["detail"]["failed_analyzers"] == ["broken"]


def test_complete_scan_exposes_status_and_scoring_version(test_repo_fixture) -> None:
    response = TestClient(app).post("/api/scan", json={"repo_path": str(test_repo_fixture)})
    assert response.status_code == 200
    data = response.json()
    assert data["scoring_version"] == SCORING_VERSION
    assert data["analyzer_execution"]
    assert all(item["status"] == "completed" for item in data["analyzer_execution"])
    assert data["penalty_explanation"]["findings"] == sorted(
        data["penalty_explanation"]["findings"],
        key=lambda item: item["finding_id"],
    )


def test_scoring_version_persists_and_round_trips_api(test_repo_fixture) -> None:
    previous = get_history_store()
    store = InMemoryHistoryStore()
    set_history_store(store)
    try:
        client = TestClient(app)
        scan = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)}).json()
        history = client.get(f"/api/history/{scan['scan_id']}")
        assert history.status_code == 200
        assert history.json()["scoring_version"] == SCORING_VERSION
    finally:
        set_history_store(previous)


def test_legacy_record_loads_without_scoring_version() -> None:
    data = {
        "scan_id": "old", "repository_id": "repo", "repository_path": "repo",
        "scanned_at": "2026-01-01T00:00:00+00:00", "schema_version": "1.0",
        "score": 700, "grade": "C", "total_debt_points": 1, "finding_count": 0,
        "category_scores": {}, "severity_distribution": {}, "findings_by_category": {},
        "findings_source_breakdown": {}, "findings": [],
    }
    assert ScanRecord.from_dict(data).scoring_version == "legacy-unversioned"


def test_unchanged_input_score_is_deterministic(test_repo_fixture) -> None:
    client = TestClient(app)
    first = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)}).json()
    second = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)}).json()
    keys = ("score", "grade", "total_debt_points", "category_scores", "scoring_version")
    assert {key: first[key] for key in keys} == {key: second[key] for key in keys}
