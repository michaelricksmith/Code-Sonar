"""Tests for /api/scan endpoint and health check."""

import pytest
from fastapi.testclient import TestClient

from app.history import InMemoryHistoryStore
from app.main import app, get_history_store, set_history_store


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root_returns_version(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "0.1.0"


class TestScanEndpoint:
    @pytest.mark.asyncio
    async def test_scan_with_valid_repo_returns_findings(self, client, test_repo_fixture):
        response = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)})
        assert response.status_code == 200
        data = response.json()
        assert "findings" in data
        assert isinstance(data["findings"], list)
        assert "summary" in data
        assert "scan_id" in data
        if data["findings"]:
            finding = data["findings"][0]
            assert "id" in finding
            assert "rule_id" in finding
            assert "file_path" in finding
            assert "severity" in finding
            assert "evidence" in finding

    def test_scan_returns_persisted_scan_id(self, client, test_repo_fixture):
        previous = get_history_store()
        store = InMemoryHistoryStore()
        set_history_store(store)
        try:
            response = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)})
            assert response.status_code == 200
            scan_id = response.json()["scan_id"]
            assert isinstance(scan_id, str)
            assert scan_id
            assert store.get(scan_id) is not None
        finally:
            set_history_store(previous)

    @pytest.mark.asyncio
    async def test_scan_with_invalid_path_returns_400(self, client):
        response = client.post("/api/scan", json={"repo_path": "/nonexistent/path/to/repo"})
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower() or "invalid" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_scan_with_missing_repo_path_returns_422(self, client):
        response = client.post("/api/scan", json={})
        assert response.status_code == 422
        assert "detail" in response.json()

    @pytest.mark.asyncio
    async def test_scan_with_file_instead_of_directory_returns_400(self, client, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        response = client.post("/api/scan", json={"repo_path": str(test_file)})
        assert response.status_code == 400
        assert "detail" in response.json()

    @pytest.mark.asyncio
    async def test_scan_returns_deterministic_results(self, client, test_repo_fixture):
        response_1 = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)})
        response_2 = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)})
        assert response_1.status_code == 200
        assert response_2.status_code == 200
        data_1 = response_1.json()
        data_2 = response_2.json()
        assert len(data_1["findings"]) == len(data_2["findings"])
        assert sorted(data_1["findings"], key=lambda f: f["id"]) == sorted(
            data_2["findings"], key=lambda f: f["id"]
        )

    @pytest.mark.asyncio
    async def test_scan_summary_contains_counts(self, client, test_repo_fixture):
        response = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)})
        assert response.status_code == 200
        summary = response.json()["summary"]
        assert "total_findings" in summary
        assert "by_severity" in summary or "by_category" in summary
        assert isinstance(summary["total_findings"], int)
        assert summary["total_findings"] >= 0

    @pytest.mark.asyncio
    async def test_scan_with_empty_repo_returns_empty_findings(self, client, tmp_path):
        response = client.post("/api/scan", json={"repo_path": str(tmp_path)})
        assert response.status_code == 200
        data = response.json()
        assert len(data["findings"]) == 0
        assert data["summary"]["total_findings"] == 0

    @pytest.mark.asyncio
    async def test_scan_response_schema_matches_openapi(self, client, test_repo_fixture):
        response = client.post("/api/scan", json={"repo_path": str(test_repo_fixture)})
        assert response.status_code == 200
        data = response.json()
        for field in ["scan_id", "findings", "summary"]:
            assert field in data, f"Response missing required field: {field}"
        for finding in data["findings"]:
            for field in [
                "id",
                "rule_id",
                "category",
                "severity",
                "confidence",
                "file_path",
                "evidence",
                "message",
                "debt_points",
                "analyzer",
            ]:
                assert field in finding, f"Finding missing required field: {field}"
