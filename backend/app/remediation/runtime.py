"""Runtime registration for remediation executors and workspace preparation."""

from __future__ import annotations

from app.remediation.contracts import DryRunRemediationExecutor, RemediationExecutor
from app.remediation.workspace import GitWorktreeManager

_executor: RemediationExecutor = DryRunRemediationExecutor()
_workspace_manager = GitWorktreeManager()


def set_remediation_executor(executor: RemediationExecutor) -> None:
    """Set the explicitly approved remediation executor implementation."""
    global _executor
    _executor = executor


def get_remediation_executor() -> RemediationExecutor:
    """Return the currently configured remediation executor."""
    return _executor


def set_workspace_manager(manager: GitWorktreeManager) -> None:
    """Override isolated Git workspace preparation; primarily used by tests."""
    global _workspace_manager
    _workspace_manager = manager


def get_workspace_manager() -> GitWorktreeManager:
    """Return the configured isolated remediation workspace manager."""
    return _workspace_manager
