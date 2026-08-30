"""Tests for isolated Git worktree preparation."""

from pathlib import Path

import pytest

from app.remediation.contracts import RemediationRequest
from app.remediation.workspace import GitCommandResult, GitWorktreeManager


class FakeGitRunner:
    def __init__(self, repository_root: Path, *, existing_branch: bool = False) -> None:
        self.repository_root = repository_root
        self.existing_branch = existing_branch
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> GitCommandResult:
        self.calls.append(args)
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return GitCommandResult(0, stdout=str(self.repository_root) + "\n")
        if args[-2:] == ["rev-parse", "HEAD"]:
            return GitCommandResult(0, stdout="abc123def456\n")
        if "branch" in args and "--list" in args:
            return GitCommandResult(0, stdout=(args[-1] + "\n") if self.existing_branch else "")
        if "worktree" in args and "add" in args:
            return GitCommandResult(0)
        return GitCommandResult(1, stderr="unexpected git command")


def _request(repository_path: Path, *, approved: bool = True) -> RemediationRequest:
    return RemediationRequest(
        request_id="request-123",
        repository_path=str(repository_path),
        finding_id="finding:oversized/function",
        scan_id="scan-1",
        instruction="Refactor the oversized function.",
        approved=approved,
    )


def test_prepare_requires_explicit_approval(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeGitRunner(repo)
    manager = GitWorktreeManager(root=tmp_path / "worktrees", runner=runner)

    with pytest.raises(PermissionError, match="explicit approval"):
        manager.prepare(_request(repo, approved=False))

    assert runner.calls == []
    assert not (tmp_path / "worktrees").exists()


def test_prepare_creates_isolated_branch_and_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeGitRunner(repo)
    worktree_root = tmp_path / "worktrees"
    manager = GitWorktreeManager(root=worktree_root, runner=runner)

    prepared = manager.prepare(_request(repo))

    assert prepared.repository_root == str(repo.resolve())
    assert prepared.base_commit == "abc123def456"
    assert prepared.branch_name.startswith("code-sonar/remediation/finding-oversized-function-")
    assert Path(prepared.workspace_path).parent == worktree_root
    assert str(repo.resolve()) != prepared.workspace_path
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
