"""Tests for isolated Git worktree preparation."""

from pathlib import Path

import pytest

from app.remediation.approval import RemediationAuthorization
from app.remediation.contracts import RemediationRequest
from app.remediation.workspace import (
    GitCommandResult,
    GitWorktreeManager,
    PreparedWorkspace,
)


class FakeGitRunner:
    def __init__(self, repository_root: Path, *, existing_branch: bool = False) -> None:
        self.repository_root = repository_root
        self.existing_branch = existing_branch
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> GitCommandResult:
        self.calls.append(args)
        result = self._rev_parse_result(args)
        if result is not None:
            return result
        result = self._branch_list_result(args)
        if result is not None:
            return result
        result = self._worktree_result(args)
        if result is not None:
            return result
        result = self._branch_delete_result(args)
        if result is not None:
            return result
        return GitCommandResult(1, stderr="unexpected git command")

    def _rev_parse_result(self, args: list[str]) -> GitCommandResult | None:
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return GitCommandResult(0, stdout=str(self.repository_root) + "\n")
        if args[-2:] == ["rev-parse", "HEAD"]:
            return GitCommandResult(0, stdout="abc123def456\n")
        return None

    def _branch_list_result(self, args: list[str]) -> GitCommandResult | None:
        if "branch" in args and "--list" in args:
            return GitCommandResult(0, stdout=(args[-1] + "\n") if self.existing_branch else "")
        return None

    def _worktree_result(self, args: list[str]) -> GitCommandResult | None:
        if "worktree" not in args:
            return None
        if "add" in args or "remove" in args:
            return GitCommandResult(0)
        return None

    def _branch_delete_result(self, args: list[str]) -> GitCommandResult | None:
        if "branch" in args and "-D" in args:
            return GitCommandResult(0)
        return None


def _request(repository_path: Path, *, approved: bool = True) -> RemediationRequest:
    return RemediationRequest(
        request_id="request-123",
        repository_path=str(repository_path),
        finding_id="finding:oversized/function",
        scan_id="scan-1",
        instruction="Refactor the oversized function.",
        approved=approved,
    )


def _prepare_workspace(tmp_path: Path) -> tuple[PreparedWorkspace, FakeGitRunner, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeGitRunner(repo)
    worktree_root = tmp_path / "worktrees"
    manager = GitWorktreeManager(root=worktree_root, runner=runner)
    return manager.prepare(_request(repo)), runner, repo, worktree_root


def test_prepare_requires_explicit_approval(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeGitRunner(repo)
    manager = GitWorktreeManager(root=tmp_path / "worktrees", runner=runner)

    with pytest.raises(PermissionError, match="explicit approval"):
        manager.prepare(_request(repo, approved=False))

    assert runner.calls == []
    assert not (tmp_path / "worktrees").exists()


def test_prepare_binds_prepared_fields(tmp_path: Path) -> None:
    prepared, _, repo, _ = _prepare_workspace(tmp_path)

    assert prepared.repository_root == str(repo.resolve())
    assert prepared.base_commit == "abc123def456"
    assert prepared.branch_name.startswith("code-sonar/remediation/finding-oversized-function-")


def test_prepare_creates_worktree_under_isolated_root(tmp_path: Path) -> None:
    prepared, _, repo, worktree_root = _prepare_workspace(tmp_path)

    assert Path(prepared.workspace_path).parent == worktree_root
    assert str(repo.resolve()) != prepared.workspace_path


def test_prepare_issues_worktree_add_command(tmp_path: Path) -> None:
    prepared, runner, repo, _ = _prepare_workspace(tmp_path)
    worktree_call = runner.calls[-1]

    assert worktree_call[:4] == ["git", "-C", str(repo.resolve()), "worktree"]
    assert "-b" in worktree_call
    assert prepared.branch_name in worktree_call
    assert prepared.workspace_path in worktree_call
    assert worktree_call[-1] == prepared.base_commit


def test_prepare_rejects_existing_remediation_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeGitRunner(repo, existing_branch=True)
    manager = GitWorktreeManager(root=tmp_path / "worktrees", runner=runner)

    with pytest.raises(FileExistsError, match="branch already exists"):
        manager.prepare(_request(repo))

    assert not any("worktree" in call and "add" in call for call in runner.calls)


def test_authorized_workspace_binds_fields_and_cleanup_removes_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeGitRunner(repo)
    manager = GitWorktreeManager(root=tmp_path / "worktrees", runner=runner)
    authorization = RemediationAuthorization(
        authorization_id="auth-1",
        request_id="request-123",
        repository_path=str(repo),
        scan_id="scan-1",
        finding_id="finding:oversized/function",
        plan_id="plan-1",
        base_commit="abc123def456",
        executor="cursor",
        remediation_kind="approved_patch",
        instruction="Refactor the oversized function.",
        expires_at=9999999999.0,
        signature="signed",
    )

    prepared = manager.prepare_authorized(authorization)
    assert prepared.scan_id == "scan-1"
    assert prepared.finding_id == "finding:oversized/function"
    assert prepared.executor == "cursor"
    assert prepared.remediation_kind == "approved_patch"
    assert prepared.authorization_id == "auth-1"

    manager.cleanup(prepared.workspace_id)
    assert manager.get(prepared.workspace_id) is None
    assert any("remove" in call for call in runner.calls)
    assert any("-D" in call for call in runner.calls)
