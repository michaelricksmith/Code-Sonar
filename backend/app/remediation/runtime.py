"""Runtime registration for remediation execution, workspaces, validation, and orchestration."""

from __future__ import annotations

import json
import os

from app.remediation.approval import RemediationAuthorizationService
from app.remediation.contracts import DryRunRemediationExecutor, RemediationExecutor
from app.remediation.cursor import CursorRemediationExecutor
from app.remediation.deterministic import DeterministicRemediationExecutor
from app.remediation.groq import GroqRemediationExecutor
from app.remediation.orchestration import RemediationOrchestrator
from app.remediation.validation import RemediationValidationService, ValidationCommand
from app.remediation.workspace import GitWorktreeManager

_executor: RemediationExecutor = DryRunRemediationExecutor()
_workspace_manager = GitWorktreeManager()
_validation_service = RemediationValidationService(workspace_root=_workspace_manager.root)
_authorization_service = RemediationAuthorizationService()


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


def set_validation_service(service: RemediationValidationService) -> None:
    """Override remediation validation/rescan behavior; primarily used by tests."""
    global _validation_service
    _validation_service = service


def get_validation_service() -> RemediationValidationService:
    """Return the configured remediation validation/rescan service."""
    return _validation_service


def get_authorization_service() -> RemediationAuthorizationService:
    return _authorization_service


def set_authorization_service(service: RemediationAuthorizationService) -> None:
    global _authorization_service
    _authorization_service = service


def get_remediation_orchestrator() -> RemediationOrchestrator:
    """Build an orchestrator from the current explicitly configured components."""
    return RemediationOrchestrator(
        workspace_manager=_workspace_manager,
        executor=_executor,
        validation_service=_validation_service,
        authorization_service=_authorization_service,
    )


def configure_remediation_executor_from_env() -> None:
    """Configure an executor explicitly from environment without running commands."""
    global _executor
    executor_name = os.getenv("CODE_SONAR_REMEDIATION_EXECUTOR", "").strip().lower()
    if executor_name == "deterministic":
        _executor = DeterministicRemediationExecutor()
        return
    if executor_name == "groq":
        _executor = GroqRemediationExecutor()
        return
    if executor_name == "cursor":
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
        return
    # Default: deterministic executor handles structural issues for free.
    # Set CODE_SONAR_REMEDIATION_EXECUTOR=cursor for AI-powered fixes.
    _executor = DeterministicRemediationExecutor()


def configure_validation_service_from_env() -> None:
    """Configure explicit build/test validation commands from a JSON array.

    ``CODE_SONAR_REMEDIATION_VALIDATORS_JSON`` accepts objects shaped as
    ``{"name":"pytest","kind":"tests","argv":["python","-m","pytest"]}``.
    Invalid configuration fails closed to a rescan-only validation service.
    Commands are argv arrays and are never executed through a shell.
    """
    global _validation_service
    raw = os.getenv("CODE_SONAR_REMEDIATION_VALIDATORS_JSON", "").strip()
    if not raw:
        _validation_service = RemediationValidationService(
            workspace_root=_workspace_manager.root
        )
        return

    try:
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("Validation configuration must be a JSON array")
        commands: list[ValidationCommand] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Validation command entries must be objects")
            name = str(item["name"]).strip()
            kind = str(item["kind"]).strip().lower()
            argv_raw = item["argv"]
            timeout_seconds = float(item.get("timeout_seconds", 300.0))
            if not name or kind not in {"build", "tests", "other"}:
                raise ValueError("Invalid validation command name or kind")
            if not isinstance(argv_raw, list) or not argv_raw:
                raise ValueError("Validation argv must be a non-empty JSON array")
            if timeout_seconds <= 0:
                raise ValueError("Validation timeout must be positive")
            commands.append(
                ValidationCommand(
                    name=name,
                    kind=kind,  # type: ignore[arg-type]
                    argv=tuple(str(token) for token in argv_raw),
                    timeout_seconds=timeout_seconds,
                )
            )
        _validation_service = RemediationValidationService(
            commands=tuple(commands),
            workspace_root=_workspace_manager.root,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        _validation_service = RemediationValidationService(
            workspace_root=_workspace_manager.root
        )


configure_remediation_executor_from_env()
configure_validation_service_from_env()
