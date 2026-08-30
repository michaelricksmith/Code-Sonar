"""API tests for the controlled remediation executor boundary."""

from fastapi.testclient import TestClient

from app.main import app
from app.remediation.contracts import DryRunRemediationExecutor
from app.remediation.runtime import set_remediation_executor


def _client() -> TestClient:
    set_remediation_executor(DryRunRemediationExecutor())
    return TestClient(app)


def test_status_reports_dry_run_default() -> None:
    response = _client().get("/api/remediation/status")

    assert response.status_code == 200
    data = response.json()
    assert data["executor_name"] == "dry_run"
    assert data["dry_run_default"] is True
    assert data["deterministic_score_authority"] == "code_sonar"


def test_unapproved_execute_never_changes_files() -> None:
    response = _client().post(
        "/api/remediation/execute",
        json={
            "request_id": "request-1",
            "repository_path": "example/repo",
            "finding_id": "finding-1",
            "scan_id": "scan-1",
            "instruction": "Remove the stale TODO safely.",
            "approved": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["request"]["approved"] is False
    assert data["result"]["state"] == "dry_run"
    assert data["result"]["changed_files"] == []
    assert "not approved" in data["result"]["summary"]
    assert data["deterministic_score_unchanged"] is True


def test_approved_dry_run_still_makes_no_repository_changes() -> None:
    response = _client().post(
        "/api/remediation/execute",
        json={
            "request_id": "request-2",
            "repository_path": "example/repo",
            "finding_id": "finding-2",
            "scan_id": "scan-2",
            "instruction": "Refactor the oversized function.",
            "approved": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["request"]["approved"] is True
    assert data["result"]["executor_name"] == "dry_run"
    assert data["result"]["state"] == "dry_run"
    assert data["result"]["changed_files"] == []
    assert "no files were changed" in data["result"]["summary"]
