"""Runtime registration for remediation executors."""

from __future__ import annotations

from app.remediation.contracts import DryRunRemediationExecutor, RemediationExecutor

_executor: RemediationExecutor = DryRunRemediationExecutor()


def set_remediation_executor(executor: RemediationExecutor) -> None:
    """Set the explicitly approved remediation executor implementation."""
    global _executor
    _executor = executor


def get_remediation_executor() -> RemediationExecutor:
    """Return the currently configured remediation executor."""
    return _executor
