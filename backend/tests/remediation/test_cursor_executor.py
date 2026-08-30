"""Tests for the isolated Cursor remediation executor."""

from pathlib import Path

from app.remediation.contracts import RemediationExecutionState, RemediationRequest
from app.remediation.cursor import CursorRemediationExecutor, ProcessResult


def _request(workspace: Path, *, approved: bool = True) -> RemediationRequest:
    return RemediationRequest(
        request_id="request-1",
        repository_path=str(workspace),
        finding_id="finding-1",
        scan_id="scan-1",
        instruction="Remove the stale TODO without changing public behavior.",
        approved=approved,
    )


def test_unapproved_cursor_request_never_runs_a_command(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args: list[str], cwd: Path, timeout: float) -> ProcessResult:
        calls.append(args)
        return ProcessResult(0)

    executor = CursorRemediationExecutor(
        ("cursor-agent", "--workspace", "{workspace}", "--prompt", "{instruction}"),
        workspace_root=tmp_path,
        runner=runner,
    )

    result = executor.execute(_request(tmp_path / "missing", approved=False))

    assert result.state is RemediationExecutionState.DRY_RUN
    assert result.changed_files == ()
    assert calls == []


def test_cursor_blocks_paths_outside_remediation_root(tmp_path: Path) -> None:
    workspace_root = tmp_path / "managed"
    outside = tmp_path / "outside"
    outside.mkdir()
    calls: list[list[str]] = []

    def runner(args: list[str], cwd: Path, timeout: float) -> ProcessResult:
        calls.append(args)
        return ProcessResult(0)

    executor = CursorRemediationExecutor(
        ("cursor-agent", "{workspace}", "{instruction}"),
        workspace_root=workspace_root,
        runner=runner,
    )

    result = executor.execute(_request(outside))

    assert result.state is RemediationExecutionState.FAILED
    assert "only inside Code Sonar remediation worktrees" in (result.error or "")
    assert calls == []


def test_cursor_runs_only_in_verified_worktree_and_reports_git_changes(tmp_path: Path) -> None:
    workspace_root = tmp_path / "managed"
    workspace = workspace_root / "abc123"
    workspace.mkdir(parents=True)
    calls: list[tuple[list[str], Path, float]] = []

    def runner(args: list[str], cwd: Path, timeout: float) -> ProcessResult:
        calls.append((args, cwd, timeout))
        if args == ["git", "rev-parse", "--show-toplevel"]:
            return ProcessResult(0, stdout=str(workspace) + "\n")
        if args == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return ProcessResult(0, stdout="code-sonar/remediation/finding-request-abc123\n")
        if args == ["git", "diff", "--name-only", "HEAD"]:
            return ProcessResult(0, stdout="src/changed.py\n")
        if args == ["git", "ls-files", "--others", "--exclude-standard"]:
            return ProcessResult(0, stdout="src/new.py\n")
        if args[0] == "cursor-agent":
            return ProcessResult(0, stdout="agent output is intentionally ignored")
        raise AssertionError(f"Unexpected command: {args}")

    executor = CursorRemediationExecutor(
        (
            "cursor-agent",
            "--workspace",
            "{workspace}",
            "--prompt",
            "{instruction}",
        ),
        workspace_root=workspace_root,
        runner=runner,
        timeout_seconds=321,
    )

    request = _request(workspace)
    result = executor.execute(request)

    assert result.state is RemediationExecutionState.EXECUTED
    assert result.changed_files == ("src/changed.py", "src/new.py")
    agent_calls = [call for call in calls if call[0][0] == "cursor-agent"]
    assert len(agent_calls) == 1
    agent_args, agent_cwd, agent_timeout = agent_calls[0]
    assert agent_cwd == workspace
    assert agent_timeout == 321
    assert str(workspace) in agent_args
    assert request.instruction in agent_args
