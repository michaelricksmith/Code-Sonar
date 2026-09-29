"""Unit and route tests for ``app.main`` (the FastAPI application entrypoint).

``tests/api/test_scan.py`` already covers the ``/health``, ``/``, and
``/api/scan`` happy paths, and ``tests/api/test_project_dashboard.py``
covers ``/api/projects/{id}/dashboard``. This file fills the remaining
gaps in ``app/main.py`` without duplicating those tests:

- the private record helpers (``_record_to_dict``,
  ``_record_public_dict``, ``_record_summary``,
  ``_record_public_summary``), especially the repository-path stripping
  contract used by every public history response;
- ``_build_scan_response`` (summary contract, ``detected_at`` exclusion,
  hotspot/execution pass-through);
- the history-store plumbing (``get_history_store``/``set_history_store``);
- ``_spa_index`` and the ``/app`` route when the dashboard is not built;
- the ``/api/analyzers`` route contract;
- model validation and the invalid-path (400) branches of
  ``/api/scan`` and ``/api/hotspots``.

Companion file ``tests/test_main_history.py`` covers the history
routes and the ``/api/drift`` route.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.history import (
    InMemoryHistoryStore,
    ScanRecord,
    build_scan_record,
    compute_repository_id,
    compute_repository_id_for_slug,
)
from app.main import (
    ScanRequest,
    _build_scan_response,
    _record_public_dict,
    _record_public_summary,
    _record_summary,
    _record_to_dict,
    _spa_index,
    app,
    get_history_store,
    set_history_store,
)
from app.models.finding import Finding
from app.scoring.engine import SCORING_VERSION, ScoringResult


def _mk_scoring() -> ScoringResult:
    return ScoringResult(
        score=72,
        grade="C",
        total_debt_points=14,
        finding_count=3,
        category_scores={"maintainability": 72},
        severity_distribution={"info": 1, "warning": 2},
        findings_by_category={"maintainability": 3},
        findings_source_breakdown={"comment_markers": 3},
        penalty_explanation={"total_penalty": 28},
    )


def _mk_record(
    *,
    scan_id: str,
    repository_id: str,
    findings: list[Finding],
    scanned_at: str,
) -> ScanRecord:
    return build_scan_record(
        repository_id=repository_id,
        repository_path="/tmp/fake-repo",
        findings=findings,
        scoring=_mk_scoring(),
        scan_id=scan_id,
        scanned_at=scanned_at,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def history_store() -> InMemoryHistoryStore:
    """Swap in a fresh in-memory history store, restoring it afterwards."""
    previous = get_history_store()
    store = InMemoryHistoryStore()
    set_history_store(store)
    yield store
    set_history_store(previous)


class TestRecordToDict:
    def test_keeps_all_persisted_fields(self, sample_findings_fixture):
        record = _mk_record(
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        data = _record_to_dict(record)
        assert data["scan_id"] == "scan-a"
        assert data["repository_id"] == "repo-a"
        assert data["repository_path"] == "/tmp/fake-repo"
        assert data["score"] == 72
        assert data["grade"] == "C"
        assert data["finding_count"] == 3
        assert len(data["findings"]) == 3

    def test_serializes_findings_to_dicts(self, sample_findings_fixture):
        record = _mk_record(
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        data = _record_to_dict(record)
        assert data["findings"][0]["id"] == "finding_001"
        assert data["findings"][0]["rule_id"] == "comment:todo"

    def test_public_dict_strips_repository_path(self, sample_findings_fixture):
        record = _mk_record(
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        data = _record_public_dict(record)
        assert "repository_path" not in data
        assert data["scan_id"] == "scan-a"
        assert data["score"] == 72
        assert len(data["findings"]) == 3


class TestRecordSummary:
    def test_summary_omits_findings(self, sample_findings_fixture):
        record = _mk_record(
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        data = _record_summary(record)
        assert "findings" not in data
        assert data["finding_count"] == 3
        assert data["repository_path"] == "/tmp/fake-repo"
        assert data["severity_distribution"] == {"info": 1, "warning": 2}

    def test_public_summary_strips_repository_path(self, sample_findings_fixture):
        record = _mk_record(
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        data = _record_public_summary(record)
        assert "repository_path" not in data
        assert "findings" not in data
        assert data["scan_id"] == "scan-a"


class TestBuildScanResponse:
    def test_fields_mirror_scoring(self, sample_findings_fixture):
        response = _build_scan_response(
            repository_label="fake-repo",
            findings=sample_findings_fixture,
            scoring_result=_mk_scoring(),
            scanned_at="2026-09-20T00:00:00+00:00",
            scan_id="scan-a",
            analyzer_execution=[{"analyzer": "comment_markers", "status": "ok"}],
        )
        assert response.repository == "fake-repo"
        assert response.scan_id == "scan-a"
        assert response.score == 72
        assert response.grade == "C"
        assert response.scoring_version == SCORING_VERSION
        assert response.total_debt_points == 14
        assert response.finding_count == 3

    def test_summary_contract(self, sample_findings_fixture):
        response = _build_scan_response(
            repository_label="fake-repo",
            findings=sample_findings_fixture,
            scoring_result=_mk_scoring(),
            scanned_at="2026-09-20T00:00:00+00:00",
            scan_id="scan-a",
            analyzer_execution=[],
        )
        assert response.summary["total_findings"] == 3
        assert response.summary["total_debt_points"] == 14
        assert response.summary["score"] == 72
        assert response.summary["grade"] == "C"
        assert response.summary["by_severity"] == {"info": 1, "warning": 2}
        assert response.summary["by_category"] == {"maintainability": 3}

    def test_findings_exclude_detected_at(self, sample_findings_fixture):
        response = _build_scan_response(
            repository_label="fake-repo",
            findings=sample_findings_fixture,
            scoring_result=_mk_scoring(),
            scanned_at="2026-09-20T00:00:00+00:00",
            scan_id=None,
            analyzer_execution=[],
        )
        assert "detected_at" not in response.findings[0]
        assert "detected_at" not in response.findings[1]
        assert "detected_at" not in response.findings[2]
        assert response.findings[0]["id"] == "finding_001"

    def test_hotspots_and_execution_pass_through(self, sample_findings_fixture):
        execution = [{"analyzer": "comment_markers", "status": "ok"}]
        response = _build_scan_response(
            repository_label="fake-repo",
            findings=sample_findings_fixture,
            scoring_result=_mk_scoring(),
            scanned_at="2026-09-20T00:00:00+00:00",
            scan_id=None,
            analyzer_execution=execution,
        )
        assert response.analyzer_execution == execution
        assert isinstance(response.top_hotspots, list)


class TestHistoryStorePlumbing:
    def test_set_and_get_roundtrip(self):
        previous = get_history_store()
        store = InMemoryHistoryStore()
        set_history_store(store)
        assert get_history_store() is store
        set_history_store(previous)


class TestScanModels:
    def test_scan_request_rejects_non_string_path(self):
        with pytest.raises(ValidationError):
            ScanRequest(repo_path=123)  # type: ignore[arg-type]

    def test_scan_request_rejects_missing_path(self):
        with pytest.raises(ValidationError):
            ScanRequest()  # type: ignore[call-arg]


class TestSpaIndex:
    def test_returns_none_when_dashboard_not_built(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.main.FRONTEND_DIST", tmp_path)
        assert _spa_index() is None

    def test_app_route_404_when_dashboard_not_built(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr("app.main.FRONTEND_DIST", tmp_path)
        response = client.get("/app")
        assert response.status_code == 404
        assert response.json()["detail"] == "Dashboard not built"


class TestAnalyzersRoute:
    def test_analyzers_contract(self, client):
        response = client.get("/api/analyzers")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == len(data["analyzers"])
        assert isinstance(data["analyzers"], list)


class TestScanRouteValidation:
    def test_scan_rejects_missing_directory(self, client):
        response = client.post(
            "/api/scan", json={"repo_path": "/does/not/exist-codesonar"}
        )
        assert response.status_code == 400

    def test_scan_rejects_empty_path(self, client):
        response = client.post("/api/scan", json={"repo_path": ""})
        assert response.status_code == 400

    def test_scan_rejects_missing_body_field(self, client):
        response = client.post("/api/scan", json={})
        assert response.status_code == 422


class TestHotspotsRoute:
    def test_hotspots_rejects_missing_directory(self, client):
        response = client.get(
            "/api/hotspots", params={"repo_path": "/does/not/exist-codesonar"}
        )
        assert response.status_code == 400


