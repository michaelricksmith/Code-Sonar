"""Runtime configuration tests for the Cursor remediation adapter."""

from pathlib import Path

from app.remediation.contracts import DryRunRemediationExecutor
from app.remediation.cursor import CursorRemediationExecutor
from app.remediation.runtime import (
    configure_remediation_executor_from_env,
    get_remediation_executor,
    set_workspace_manager,
)
from app.remediation.workspace import GitWorktreeManager


def test_cursor_runtime_requires_explicit_valid_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    set_workspace_manager(GitWorktreeManager(root=tmp_path / "worktrees"))

    monkeypatch.setenv("CODE_SONAR_REMEDIATION_EXECUTOR", "cursor")
    monkeypatch.delenv("CODE_SONAR_CURSOR_COMMAND_JSON", raising=False)
    configure_remediation_executor_from_env()
    assert isinstance(get_remediation_executor(), DryRunRemediationExecutor)

    monkeypatch.setenv("CODE_SONAR_CURSOR_COMMAND_JSON", "not-json")
    configure_remediation_executor_from_env()
    assert isinstance(get_remediation_executor(), DryRunRemediationExecutor)

    monkeypatch.setenv(
        "CODE_SONAR_CURSOR_COMMAND_JSON",
        '["cursor-agent","--workspace","{workspace}","--prompt","{instruction}"]',
    )
    configure_remediation_executor_from_env()
    executor = get_remediation_executor()
    assert isinstance(executor, CursorRemediationExecutor)
    assert executor.workspace_root == (tmp_path / "worktrees").resolve()

    monkeypatch.delenv("CODE_SONAR_REMEDIATION_EXECUTOR", raising=False)
    monkeypatch.delenv("CODE_SONAR_CURSOR_COMMAND_JSON", raising=False)
    configure_remediation_executor_from_env()
    assert isinstance(get_remediation_executor(), DryRunRemediationExecutor)
