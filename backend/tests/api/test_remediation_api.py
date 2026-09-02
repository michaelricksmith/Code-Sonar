"""API tests for the controlled remediation executor boundary."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.remediation.contracts import DryRunRemediationExecutor
from app.remediation.runtime import set_remediation_executor


def _client() -> TestClient:
    set_remediation_executor(DryRunRemediationExecutor())
    return TestClient(app)


def _payload(*, approved: bool) -> dict[str, object]:
    return {
        "request_id": "request-1",
        "repository_path": "example/repo",
        "finding_id": "finding-1",
        "scan_id": "scan-1",
        "instruction": "Remove the stale TODO safely.",
        "approved": approved,
    }


def test_status_reports_dry_run_default() -> None:
    response = _client().get("/api/remediation/status")

    assert response.status_code == 200
    data = response.json()
    assert data["executor_name"] == "dry_run"
    assert data["dry_run_default"] is True
    assert data["isolated_workspace_required"] is True
    assert data["opaque_workspace_ids"] is True
    assert data["deterministic_score_authority"] == "code_sonar"


@pytest.mark.parametrize("endpoint", ["workspace/prepare", "execute", "run"])
def test_legacy_caller_controlled_execution_is_closed(endpoint: str) -> None:
    response = _client().post(f"/api/remediation/{endpoint}", json=_payload(approved=True))

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "remediation_server_authorization_required"
    assert "example/repo" not in response.text
