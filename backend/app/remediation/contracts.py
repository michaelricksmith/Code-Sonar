"""Controlled remediation execution contracts.

Execution is downstream of Code Sonar findings. Implementations may propose or
apply changes only inside an explicitly prepared workspace; they never modify the
deterministic scoring authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class RemediationExecutionState(str, Enum):
    """Lifecycle state for one remediation execution request."""

    DRY_RUN = "dry_run"
    PREPARED = "prepared"
    EXECUTED = "executed"
    VALIDATED = "validated"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RemediationRequest:
    """One explicitly approved remediation target."""

    request_id: str
    repository_path: str
    finding_id: str
    scan_id: str
    instruction: str
    approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "repository_path": self.repository_path,
            "finding_id": self.finding_id,
            "scan_id": self.scan_id,
            "instruction": self.instruction,
            "approved": self.approved,
        }


@dataclass(frozen=True, slots=True)
class RemediationExecutionResult:
    """Result produced by an executor without changing Code Sonar authority."""

    request_id: str
    executor_name: str
    state: RemediationExecutionState
    changed_files: tuple[str, ...] = ()
    summary: str = ""
    build_passed: bool | None = None
    tests_passed: bool | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "executor_name": self.executor_name,
            "state": self.state.value,
            "changed_files": list(self.changed_files),
            "summary": self.summary,
            "build_passed": self.build_passed,
            "tests_passed": self.tests_passed,
            "error": self.error,
        }


class RemediationExecutor(Protocol):
    """Executor interface for downstream remediation agents/tools."""

    executor_name: str

    def execute(self, request: RemediationRequest) -> RemediationExecutionResult: ...


class DryRunRemediationExecutor:
    """No-op executor used to validate execution wiring safely."""

    executor_name = "dry_run"

    def execute(self, request: RemediationRequest) -> RemediationExecutionResult:
        if not request.approved:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.DRY_RUN,
                summary="Remediation request is not approved; no changes were attempted.",
            )

        return RemediationExecutionResult(
            request_id=request.request_id,
            executor_name=self.executor_name,
            state=RemediationExecutionState.DRY_RUN,
            summary="Dry-run executor validated the approved request; no files were changed.",
        )
