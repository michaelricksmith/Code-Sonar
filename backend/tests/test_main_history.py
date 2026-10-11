"""Route tests for ``app.main`` — history and drift endpoints.

Companion to ``tests/test_main.py`` (which covers the private record
helpers, ``_build_scan_response``, history-store plumbing, the SPA
fallback, the analyzers route, and scan/hotspot validation). This file
covers the history routes (``/api/history/list``,
``/api/history/latest``, ``/api/history/{scan_id}``) including 404
paths, and the ``/api/drift`` route: 404 with no history, 400 with a
single scan, 200 with two scans, and the repo-slug identity fallback.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.history import (
    InMemoryHistoryStore,
    ScanRecord,
    build_scan_record,
    compute_repository_id,
    compute_repository_id_for_slug,
)
from app.main import (
    app,
    get_history_store,
    set_history_store,
)
from app.models.finding import Finding
from app.scoring.engine import ScoringResult


def _mk_scoring(*, score: int = 72, grade: str = "C") -> ScoringResult:
    return ScoringResult(
        score=score,
        grade=grade,
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
    score: int = 72,
    grade: str = "C",
) -> ScanRecord:
    return build_scan_record(
        repository_id=repository_id,
        repository_path="/tmp/fake-repo",
        findings=findings,
        scoring=_mk_scoring(score=score, grade=grade),
        scan_id=scan_id,
        scanned_at=scanned_at,
        owner_user_id="test-user",
    )


def _seed(
    store: InMemoryHistoryStore,
    *,
    scan_id: str,
    repository_id: str,
    findings: list[Finding],
    scanned_at: str,
    score: int = 72,
    grade: str = "C",
) -> ScanRecord:
    record = _mk_record(
        scan_id=scan_id,
        repository_id=repository_id,
        findings=findings,
        scanned_at=scanned_at,
        score=score,
        grade=grade,
    )
    store.append(record)
    return record


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


@pytest.fixture(autouse=True)
def _signed_in_user(monkeypatch: pytest.MonkeyPatch):
    """Listings hide ownerless scans, so these route tests sign in an owner."""
    from types import SimpleNamespace

    import app.oauth as oauth_module

    monkeypatch.setattr(oauth_module, "current_user", lambda r: SimpleNamespace(id="test-user"))


class TestHistoryListRoute:
    def test_list_returns_public_summaries(self, client, history_store, sample_findings_fixture):
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        _seed(
            history_store,
            scan_id="scan-b",
            repository_id="repo-b",
            findings=sample_findings_fixture,
            scanned_at="2026-09-21T00:00:00+00:00",
        )
        response = client.get("/api/history/list")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["scans"]) == 2
        assert "repository_path" not in data["scans"][0]
        assert "repository_path" not in data["scans"][1]

    def test_list_filters_by_repository_id(self, client, history_store, sample_findings_fixture):
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        _seed(
            history_store,
            scan_id="scan-b",
            repository_id="repo-b",
            findings=sample_findings_fixture,
            scanned_at="2026-09-21T00:00:00+00:00",
        )
        response = client.get("/api/history/list", params={"repository_id": "repo-a"})
        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_list_respects_limit(self, client, history_store, sample_findings_fixture):
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        _seed(
            history_store,
            scan_id="scan-b",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-21T00:00:00+00:00",
        )
        response = client.get("/api/history/list", params={"limit": 1})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["scans"][0]["scan_id"] == "scan-b"


class TestHistoryLatestRoute:
    def test_latest_404_without_history(self, client, history_store, tmp_path):
        response = client.get("/api/history/latest", params={"repo_path": str(tmp_path)})
        assert response.status_code == 404

    def test_latest_400_for_invalid_path(self, client, history_store):
        response = client.get(
            "/api/history/latest", params={"repo_path": "/does/not/exist-codesonar"}
        )
        assert response.status_code == 400

    def test_latest_returns_public_record(
        self, client, history_store, sample_findings_fixture, tmp_path
    ):
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id=compute_repository_id(tmp_path),
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        response = client.get("/api/history/latest", params={"repo_path": str(tmp_path)})
        assert response.status_code == 200
        data = response.json()
        assert data["scan_id"] == "scan-a"
        assert "repository_path" not in data


class TestHistoryGetRoute:
    def test_get_404_for_unknown_scan_id(self, client, history_store):
        response = client.get("/api/history/no-such-scan")
        assert response.status_code == 404

    def test_get_returns_public_record(self, client, history_store, sample_findings_fixture):
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id="repo-a",
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        response = client.get("/api/history/scan-a")
        assert response.status_code == 200
        data = response.json()
        assert data["scan_id"] == "scan-a"
        assert "repository_path" not in data


class TestDriftRoute:
    def test_drift_404_without_history(self, client, history_store, tmp_path):
        response = client.get("/api/drift", params={"repo_path": str(tmp_path)})
        assert response.status_code == 404

    def test_drift_400_with_single_scan(
        self, client, history_store, sample_findings_fixture, tmp_path
    ):
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id=compute_repository_id(tmp_path),
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        response = client.get("/api/drift", params={"repo_path": str(tmp_path)})
        assert response.status_code == 400

    def test_drift_200_with_two_scans(
        self, client, history_store, sample_findings_fixture, tmp_path
    ):
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id=compute_repository_id(tmp_path),
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        _seed(
            history_store,
            scan_id="scan-b",
            repository_id=compute_repository_id(tmp_path),
            findings=[],
            scanned_at="2026-09-21T00:00:00+00:00",
        )
        response = client.get("/api/drift", params={"repo_path": str(tmp_path)})
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["baseline"]["scan_id"] == "scan-a"
        assert data["summary"]["current"]["scan_id"] == "scan-b"
        assert data["summary"]["resolved_count"] == 3

    def test_drift_supports_repo_slug_identity(
        self, client, history_store, sample_findings_fixture
    ):
        slug_id = compute_repository_id_for_slug("owner/name")
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id=slug_id,
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        _seed(
            history_store,
            scan_id="scan-b",
            repository_id=slug_id,
            findings=sample_findings_fixture,
            scanned_at="2026-09-21T00:00:00+00:00",
        )
        response = client.get("/api/drift", params={"repo_path": "owner/name"})
        assert response.status_code == 200
        assert response.json()["summary"]["current"]["scan_id"] == "scan-b"

    def test_drift_404_for_unknown_to_scan_id(
        self, client, history_store, sample_findings_fixture, tmp_path
    ):
        repository_id = compute_repository_id(tmp_path)
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id=repository_id,
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
        )
        _seed(
            history_store,
            scan_id="scan-b",
            repository_id=repository_id,
            findings=sample_findings_fixture,
            scanned_at="2026-09-21T00:00:00+00:00",
        )
        response = client.get(
            "/api/drift",
            params={"repo_path": str(tmp_path), "to_scan_id": "no-such-scan"},
        )
        assert response.status_code == 404


class TestHistoryTrendRoute:
    def test_trend_404_without_history(self, client, history_store, tmp_path):
        response = client.get("/api/history/trend", params={"repo_path": str(tmp_path)})
        assert response.status_code == 404

    def test_trend_single_scan_delta_null(
        self, client, history_store, sample_findings_fixture, tmp_path
    ):
        repository_id = compute_repository_id(tmp_path)
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id=repository_id,
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
            score=593,
            grade="C",
        )
        response = client.get("/api/history/trend", params={"repo_path": str(tmp_path)})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["delta"] is None
        point = data["points"][0]
        assert point["scan_id"] == "scan-a"
        assert point["scanned_at"] == "2026-09-20T00:00:00+00:00"
        assert point["score"] == 593
        assert point["grade"] == "C"
        assert point["finding_count"] == 3

    def test_trend_points_chronological_with_delta(
        self, client, history_store, sample_findings_fixture, tmp_path
    ):
        repository_id = compute_repository_id(tmp_path)
        for scan_id, scanned_at, score in [
            ("scan-a", "2026-09-20T00:00:00+00:00", 600),
            ("scan-b", "2026-09-21T00:00:00+00:00", 640),
            ("scan-c", "2026-09-22T00:00:00+00:00", 620),
        ]:
            _seed(
                history_store,
                scan_id=scan_id,
                repository_id=repository_id,
                findings=sample_findings_fixture,
                scanned_at=scanned_at,
                score=score,
            )
        response = client.get("/api/history/trend", params={"repo_path": str(tmp_path)})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert [p["score"] for p in data["points"]] == [600, 640, 620]
        assert [p["scan_id"] for p in data["points"]] == ["scan-a", "scan-b", "scan-c"]
        assert data["delta"] == -20

    def test_trend_respects_limit(
        self, client, history_store, sample_findings_fixture, tmp_path
    ):
        repository_id = compute_repository_id(tmp_path)
        for i in range(5):
            _seed(
                history_store,
                scan_id=f"scan-{i}",
                repository_id=repository_id,
                findings=sample_findings_fixture,
                scanned_at=f"2026-09-2{i}T00:00:00+00:00",
                score=600 + i,
            )
        response = client.get(
            "/api/history/trend", params={"repo_path": str(tmp_path), "limit": 2}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert [p["scan_id"] for p in data["points"]] == ["scan-3", "scan-4"]
        assert data["delta"] == 1

    def test_trend_supports_repo_slug_identity(
        self, client, history_store, sample_findings_fixture
    ):
        slug_id = compute_repository_id_for_slug("owner/name")
        _seed(
            history_store,
            scan_id="scan-a",
            repository_id=slug_id,
            findings=sample_findings_fixture,
            scanned_at="2026-09-20T00:00:00+00:00",
            score=600,
        )
        _seed(
            history_store,
            scan_id="scan-b",
            repository_id=slug_id,
            findings=sample_findings_fixture,
            scanned_at="2026-09-21T00:00:00+00:00",
            score=650,
        )
        response = client.get("/api/history/trend", params={"repo_path": "owner/name"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert data["delta"] == 50
