"""Controlled remediation orchestration invariants."""

from pathlib import Path

from app.remediation.approval import RemediationAuthorization
from app.remediation.contracts import (
    RemediationExecutionResult,
    RemediationExecutionState,
    RemediationRequest,
)
from app.remediation.orchestration import RemediationOrchestrator
from app.remediation.validation import RemediationValidationResult
from app.remediation.workspace import PreparedWorkspace


class FakeWorkspaceManager:
    def __init__(self, workspace_path: str) -> None:
        self.workspace_path = workspace_path
        self.prepare_calls = 0
        self.cleanup_calls: list[str] = []

    def prepare_authorized(self, authorization: RemediationAuthorization) -> PreparedWorkspace:
        self.prepare_calls += 1
        return PreparedWorkspace(
            workspace_id="ws_test",
            request_id=authorization.request_id,
            repository_root=authorization.repository_path,
            workspace_path=self.workspace_path,
            branch_name="code-sonar/remediation/finding-request-deadbeef00",
            base_commit=authorization.base_commit,
            scan_id=authorization.scan_id,
            finding_id=authorization.finding_id,
            executor=authorization.executor,
            remediation_kind=authorization.remediation_kind,
            authorization_id=authorization.authorization_id,
        )

    def cleanup(self, workspace_id: str) -> None:
        self.cleanup_calls.append(workspace_id)


class FakeAuthorizationService:
    def __init__(self) -> None:
        self.consumed: list[str] = []

    def consume(self, authorization: RemediationAuthorization) -> None:
        self.consumed.append(authorization.authorization_id)


class FakeExecutor:
    executor_name = "fake"

    def __init__(self, state: RemediationExecutionState) -> None:
        self.state = state
        self.requests: list[RemediationRequest] = []

    def execute(self, request: RemediationRequest) -> RemediationExecutionResult:
        self.requests.append(request)
        return RemediationExecutionResult(
            request_id=request.request_id,
            executor_name=self.executor_name,
            state=self.state,
            changed_files=("src/a.py",) if self.state is RemediationExecutionState.EXECUTED else (),
            summary="fake result",
        )


class FakeValidationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def validate(self, **kwargs: object) -> RemediationValidationResult:
        self.calls.append(kwargs)
        return RemediationValidationResult(
            request_id=str(kwargs["request_id"]),
            before_scan_id=str(kwargs["before_scan_id"]),
            after_scan_id="scan-after",
            outcome_id="outcome-1",
            finding_resolved=True,
            regression_detected=False,
            score_delta=3,
            debt_points_delta=-4,
            build_passed=True,
            tests_passed=True,
            command_results=(),
            training_label_value="1",
            training_label_trust_tier="remediation_outcome",
        )


def _request(*, approved: bool = True) -> RemediationRequest:
    return RemediationRequest(
        request_id="request-1",
        repository_path="/active/repo",
        finding_id="finding-1",
        scan_id="scan-before",
        instruction="Fix the finding safely.",
        approved=approved,
    )


def _authorization() -> RemediationAuthorization:
    return RemediationAuthorization(
        authorization_id="auth-1",
        request_id="request-1",
        repository_path="/active/repo",
        scan_id="scan-before",
        finding_id="finding-1",
        plan_id="plan-1",
        base_commit="abc123",
        executor="fake",
        remediation_kind="cursor_patch",
        instruction="Fix the finding safely.",
        expires_at=9999999999.0,
        signature="signed",
    )


def test_unapproved_workflow_stops_before_workspace_preparation() -> None:
    manager = FakeWorkspaceManager("/isolated/worktree")
    executor = FakeExecutor(RemediationExecutionState.EXECUTED)
    validator = FakeValidationService()
    orchestrator = RemediationOrchestrator(
        workspace_manager=manager,  # type: ignore[arg-type]
        executor=executor,
        validation_service=validator,  # type: ignore[arg-type]
        authorization_service=FakeAuthorizationService(),  # type: ignore[arg-type]
    )

    try:
        orchestrator.run(_request(approved=False))
    except PermissionError:
        pass
    else:
        raise AssertionError("unapproved orchestration should be rejected")

    assert manager.prepare_calls == 0
    assert executor.requests == []
    assert validator.calls == []


def test_execution_failure_prevents_validation() -> None:
    manager = FakeWorkspaceManager("/isolated/worktree")
    executor = FakeExecutor(RemediationExecutionState.FAILED)
    validator = FakeValidationService()
    orchestrator = RemediationOrchestrator(
        workspace_manager=manager,  # type: ignore[arg-type]
        executor=executor,
        validation_service=validator,  # type: ignore[arg-type]
        authorization_service=FakeAuthorizationService(),  # type: ignore[arg-type]
    )

    result = orchestrator.run_authorized(_authorization())

    assert result.completed is False
    assert result.stopped_at == "execution"
    assert result.validation is None
    assert validator.calls == []
    assert executor.requests[0].repository_path == "/isolated/worktree"
    assert result.workspace is not None
    assert result.workspace.to_dict()["workspace_id"] == "ws_test"
    assert "workspace_path" not in result.workspace.to_dict()
    assert manager.cleanup_calls == ["ws_test"]


def test_successful_execution_advances_to_validation_with_isolated_workspace() -> None:
    workspace = str(Path("/isolated/worktree"))
    manager = FakeWorkspaceManager(workspace)
    executor = FakeExecutor(RemediationExecutionState.EXECUTED)
    validator = FakeValidationService()
    orchestrator = RemediationOrchestrator(
        workspace_manager=manager,  # type: ignore[arg-type]
        executor=executor,
        validation_service=validator,  # type: ignore[arg-type]
        authorization_service=FakeAuthorizationService(),  # type: ignore[arg-type]
    )

    result = orchestrator.run_authorized(_authorization())

    assert result.completed is True
    assert result.stopped_at is None
    assert result.validation is not None
    assert result.validation.outcome_id == "outcome-1"
    assert result.validation.training_label_value == "1"
    assert executor.requests[0].repository_path == workspace
    assert validator.calls[0]["workspace_path"] == workspace
    assert validator.calls[0]["before_scan_id"] == "scan-before"
    assert validator.calls[0]["finding_id"] == "finding-1"
    assert validator.calls[0]["executor"] == "fake"
    assert validator.calls[0]["remediation_kind"] == "cursor_patch"
    assert manager.cleanup_calls == ["ws_test"]
