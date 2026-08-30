"""Runtime registration for remediation executors and workspace preparation."""

from __future__ import annotations

import json
import os

from app.remediation.contracts import DryRunRemediationExecutor, RemediationExecutor
from app.remediation.cursor import CursorRemediationExecutor
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


def configure_remediation_executor_from_env() -> None:
    """Configure an executor explicitly from environment without running commands.

    Cursor activation requires both ``CODE_SONAR_REMEDIATION_EXECUTOR=cursor`` and
    ``CODE_SONAR_CURSOR_COMMAND_JSON`` containing a JSON array of argv tokens. The
    template must include ``{workspace}`` and ``{instruction}`` placeholders. Any
    invalid or incomplete configuration fails closed to the dry-run executor.
    """
    global _executor
    executor_name = os.getenv("CODE_SONAR_REMEDIATION_EXECUTOR", "").strip().lower()
    if executor_name != "cursor":
        _executor = DryRunRemediationExecutor()
        return

    raw_command = os.getenv("CODE_SONAR_CURSOR_COMMAND_JSON", "").strip()
    if not raw_command:
        _executor = DryRunRemediationExecutor()
        return

    try:
        payload = json.loads(raw_command)
        if not isinstance(payload, list) or not payload:
            raise ValueError("Cursor command must be a non-empty JSON array")
        command_template = tuple(str(token) for token in payload)
        timeout_seconds = float(os.getenv("CODE_SONAR_CURSOR_TIMEOUT_SECONDS", "900"))
        if timeout_seconds <= 0:
            raise ValueError("Cursor timeout must be positive")
        _executor = CursorRemediationExecutor(
            command_template,
            workspace_root=_workspace_manager.root,
            timeout_seconds=timeout_seconds,
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        _executor = DryRunRemediationExecutor()


configure_remediation_executor_from_env()
