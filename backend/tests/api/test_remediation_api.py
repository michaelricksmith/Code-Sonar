"""API tests for the controlled remediation executor boundary."""

from fastapi.testclient import TestClient

from app.main import app
from app.remediation.contracts import DryRunRemediationExecutor, RemediationRequest
from app.remediation.runtime import set_remediation_executor, set_workspace_manager
from app.remediation.workspace import GitWorktreeManager, PreparedWorkspace


class ApprovedWorkspaceManager(GitWorktreeManager):
    def prepare(self, request: RemediationRequest) -> PreparedWorkspace:
        if not request.approved:
            raise PermissionError("Remediation workspace preparation requires explicit approval")
        return PreparedWorkspace(
            request_id=request.request_id,
            repository_root="/repo",
            workspace_path="/isolated/worktree",
            branch_name="code-sonar/remediation/finding-request-abc123",
            base_commit="abc123",
        )


def _client() -> TestClient:
    set_remediation_executor(DryRunRemediationExecutor())
    set_workspace_manager(ApprovedWorkspaceManager())
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
    assert data["deterministic_score_authority"] == "code_sonar"


def test_workspace_prepare_requires_explicit_approval() -> None:
    response = _client().post("/api/remediation/workspace/prepare", json=_payload(approved=False))

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "remediation_approval_required"


def test_workspace_prepare_returns_isolated_location_without_execution() -> None:
    response = _client().post("/api/remediation/workspace/prepare", json=_payload(approved=True))

    assert response.status_code == 200
    data = response.json()
    assert data["request"]["approved"] is True
    assert data["workspace"]["workspace_path"] == "/isolated/worktree"
    assert data["workspace"]["repository_root"] == "/repo"
    assert data["workspace"]["branch_name"].startswith("code-sonar/remediation/")
    assert data["execution_performed"] is False
    assert data["active_checkout_modified"] is False
    assert data["deterministic_score_unchanged"] is True


def test_unapproved_execute_never_changes_files() -> None:
    response = _client().post("/api/remediation/execute", json=_payload(approved=False))

    assert response.status_code == 200
    data = response.json()
    assert data["request"]["approved"] is False
    assert data["result"]["state"] == "dry_run"
    assert data["result"]["changed_files"] == []
    assert "not approved" in data["result"]["summary"]
    assert data["deterministic_score_unchanged"] is True


def test_approved_dry_run_still_makes_no_repository_changes() -> None:
    payload = _payload(approved=True)
    payload["request_id"] = "request-2"
    payload["finding_id"] = "finding-2"
    payload["scan_id"] = "scan-2"
    payload["instruction"] = "Refactor the oversized function."
    response = _client().post("/api/remediation/execute", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["request"]["approved"] is True
    assert data["result"]["executor_name"] == "dry_run"
    assert data["result"]["state"] == "dry_run"
    assert data["result"]["changed_files"] == []
    assert "no files were changed" in data["result"]["summary"]
