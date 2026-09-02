"""Single controlled workflow for approved remediation requests."""

from __future__ import annotations

from dataclasses import dataclass

from app.remediation.approval import (
    RemediationAuthorization,
    RemediationAuthorizationService,
)
from app.remediation.contracts import (
    RemediationExecutionResult,
    RemediationExecutionState,
    RemediationExecutor,
    RemediationRequest,
)
from app.remediation.validation import (
    RemediationValidationResult,
    RemediationValidationService,
)
from app.remediation.workspace import GitWorktreeManager, PreparedWorkspace


@dataclass(frozen=True, slots=True)
class RemediationWorkflowResult:
    """Consolidated result from one remediation orchestration attempt."""

    request_id: str
    workspace: PreparedWorkspace | None
    execution: RemediationExecutionResult | None
    validation: RemediationValidationResult | None
    completed: bool
    stopped_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "workspace": self.workspace.to_dict() if self.workspace else None,
            "execution": self.execution.to_dict() if self.execution else None,
            "validation": self.validation.to_dict() if self.validation else None,
            "completed": self.completed,
            "stopped_at": self.stopped_at,
            "active_checkout_modified": False,
            "deterministic_score_authority": "code_sonar",
        }


class RemediationOrchestrator:
    """Coordinate workspace preparation, execution, validation, and outcome capture."""

    def __init__(
        self,
        *,
        workspace_manager: GitWorktreeManager,
        executor: RemediationExecutor,
        validation_service: RemediationValidationService,
        authorization_service: RemediationAuthorizationService,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.executor = executor
        self.validation_service = validation_service
        self.authorization_service = authorization_service

    def run(
        self,
        request: RemediationRequest,
        *,
        remediation_kind: str = "automated_patch",
    ) -> RemediationWorkflowResult:
        raise PermissionError(
            "Direct remediation requests are disabled; server authorization required"
        )

    def run_authorized(
        self,
        authorization: RemediationAuthorization,
    ) -> RemediationWorkflowResult:
        """Consume one immutable capability and clean its workspace on every exit."""
        if self.executor.executor_name != authorization.executor:
            raise PermissionError("Configured executor changed after remediation approval")
        self.authorization_service.consume(authorization)
        workspace: PreparedWorkspace | None = None
        try:
            workspace = self.workspace_manager.prepare_authorized(authorization)
            isolated_request = RemediationRequest(
                request_id=authorization.request_id,
                repository_path=workspace.workspace_path,
                finding_id=authorization.finding_id,
                scan_id=authorization.scan_id,
                instruction=authorization.instruction,
                approved=True,
            )
            execution = self.executor.execute(isolated_request)

            if execution.state is not RemediationExecutionState.EXECUTED:
                return RemediationWorkflowResult(
                    request_id=authorization.request_id,
                    workspace=workspace,
                    execution=execution,
                    validation=None,
                    completed=False,
                    stopped_at="execution",
                )

            validation = self.validation_service.validate(
                request_id=authorization.request_id,
                workspace_path=workspace.workspace_path,
                before_scan_id=authorization.scan_id,
                finding_id=authorization.finding_id,
                executor=authorization.executor,
                remediation_kind=authorization.remediation_kind,
            )
            return RemediationWorkflowResult(
                request_id=authorization.request_id,
                workspace=workspace,
                execution=execution,
                validation=validation,
                completed=True,
            )
        finally:
            if workspace is not None:
                self.workspace_manager.cleanup(workspace.workspace_id)
