"""Tests for /api/scan endpoint and health check.

Tests verify:
- POST /api/scan with valid repository path
- POST /api/scan with invalid path returns 400
- Health endpoint returns ok
- API response schema validation
"""


import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Create FastAPI test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Test suite for health check endpoint."""

    def test_health_returns_ok(self, client):
        """Test that /health endpoint returns ok status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_root_returns_version(self, client):
        """Test that root endpoint returns API info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert data["version"] == "0.1.0"


class TestScanEndpoint:
    """Test suite for /api/scan endpoint."""

    @pytest.mark.asyncio
    async def test_scan_with_valid_repo_returns_findings(self, client, test_repo_fixture):
        """Test POST /api/scan with valid repository path."""
        response = client.post(
            "/api/scan",
            json={"repo_path": str(test_repo_fixture)}
        )

        assert response.status_code == 200
        data = response.json()

        # Should return scan results with findings
        assert "findings" in data
        assert isinstance(data["findings"], list)
        assert "summary" in data

        # If comment_markers analyzer is implemented, should find markers
        # in test_repo_fixture
        if len(data["findings"]) > 0:
            finding = data["findings"][0]
            assert "id" in finding
            assert "rule_id" in finding
            assert "file_path" in finding
            assert "severity" in finding
            assert "evidence" in finding

    @pytest.mark.asyncio
    async def test_scan_with_invalid_path_returns_400(self, client):
        """Test POST /api/scan with non-existent path returns 400."""
        response = client.post(
            "/api/scan",
            json={"repo_path": "/nonexistent/path/to/repo"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower() or "invalid" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_scan_with_missing_repo_path_returns_422(self, client):
        """Test POST /api/scan without repo_path returns 422 validation error."""
        response = client.post(
            "/api/scan",
            json={}
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_scan_with_file_instead_of_directory_returns_400(self, client, tmp_path):
        """Test POST /api/scan with file path instead of directory returns 400."""
        # Create a file
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        response = client.post(
            "/api/scan",
            json={"repo_path": str(test_file)}
        )

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_scan_returns_deterministic_results(self, client, test_repo_fixture):
        """Test that scanning the same repo twice returns identical results."""
        # First scan
        response_1 = client.post(
            "/api/scan",
            json={"repo_path": str(test_repo_fixture)}
        )
        assert response_1.status_code == 200
        data_1 = response_1.json()

        # Second scan
        response_2 = client.post(
            "/api/scan",
            json={"repo_path": str(test_repo_fixture)}
        )
        assert response_2.status_code == 200
        data_2 = response_2.json()

        # Should return same number of findings
        assert len(data_1["findings"]) == len(data_2["findings"])

        # Findings should be identical (order may vary)
        findings_1_sorted = sorted(data_1["findings"], key=lambda f: f["id"])
        findings_2_sorted = sorted(data_2["findings"], key=lambda f: f["id"])

        assert findings_1_sorted == findings_2_sorted

    @pytest.mark.asyncio
    async def test_scan_summary_contains_counts(self, client, test_repo_fixture):
        """Test that scan response includes summary with finding counts."""
        response = client.post(
            "/api/scan",
            json={"repo_path": str(test_repo_fixture)}
        )

        assert response.status_code == 200
        data = response.json()

        assert "summary" in data
        summary = data["summary"]

        # Should include counts
        assert "total_findings" in summary
        assert "by_severity" in summary or "by_category" in summary
        assert isinstance(summary["total_findings"], int)
        assert summary["total_findings"] >= 0

    @pytest.mark.asyncio
    async def test_scan_with_empty_repo_returns_empty_findings(self, client, tmp_path):
        """Test POST /api/scan with empty repository returns no findings."""
        response = client.post(
            "/api/scan",
            json={"repo_path": str(tmp_path)}
        )

        assert response.status_code == 200
        data = response.json()

        assert "findings" in data
        assert len(data["findings"]) == 0
        assert data["summary"]["total_findings"] == 0

    @pytest.mark.asyncio
    async def test_scan_response_schema_matches_openapi(self, client, test_repo_fixture):
        """Test that scan response matches OpenAPI schema."""
        response = client.post(
            "/api/scan",
            json={"repo_path": str(test_repo_fixture)}
        )

        assert response.status_code == 200
        data = response.json()

        # Required top-level fields
        required_fields = ["findings", "summary"]
        for field in required_fields:
            assert field in data, f"Response missing required field: {field}"

        # Each finding should have required fields
        for finding in data["findings"]:
            required_finding_fields = [
                "id", "rule_id", "category", "severity", "confidence",
                "file_path", "evidence", "message", "debt_points", "analyzer"
            ]
            for field in required_finding_fields:
                assert field in finding, f"Finding missing required field: {field}"
