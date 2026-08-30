"""Isolated Git worktree preparation for approved remediation requests."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.remediation.contracts import RemediationRequest

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


GitCommandRunner = Callable[[list[str]], GitCommandResult]


@dataclass(frozen=True, slots=True)
class PreparedWorkspace:
    request_id: str
    repository_root: str
    workspace_path: str
    branch_name: str
    base_commit: str

    def to_dict(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "repository_root": self.repository_root,
            "workspace_path": self.workspace_path,
            "branch_name": self.branch_name,
            "base_commit": self.base_commit,
        }


def _default_git_runner(args: list[str]) -> GitCommandResult:
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return GitCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _safe_token(value: str, *, fallback: str) -> str:
    cleaned = _SAFE_TOKEN.sub("-", value.strip()).strip("-._")
    return cleaned[:48] or fallback


class GitWorktreeManager:
    """Prepare disposable remediation worktrees without editing the active checkout."""

    def __init__(
        self,
        root: Path | None = None,
        runner: GitCommandRunner = _default_git_runner,
    ) -> None:
        self.root = root or (Path.home() / ".code-sonar" / "remediation-worktrees")
        self.runner = runner

    def _run(self, args: list[str], *, failure: str) -> GitCommandResult:
        result = self.runner(args)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(failure + suffix)
        return result

    def prepare(self, request: RemediationRequest) -> PreparedWorkspace:
        if not request.approved:
            raise PermissionError("Remediation workspace preparation requires explicit approval")

        repo = Path(request.repository_path).expanduser().resolve()
        if not repo.exists() or not repo.is_dir():
            raise ValueError("Remediation repository path does not exist or is not a directory")

        top_level = self._run(
            ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
            failure="Target is not a valid Git repository",
        ).stdout.strip()
        if not top_level:
            raise RuntimeError("Git repository root could not be resolved")

        repository_root = Path(top_level).resolve()
        base_commit = self._run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            failure="Could not resolve remediation base commit",
        ).stdout.strip()
        if not base_commit:
            raise RuntimeError("Remediation base commit could not be resolved")

        request_token = _safe_token(request.request_id, fallback="request")
        finding_token = _safe_token(request.finding_id, fallback="finding")
        digest = hashlib.sha256(
            f"{repository_root}|{request.request_id}|{request.finding_id}|{base_commit}".encode("utf-8")
        ).hexdigest()[:10]
        branch_name = f"code-sonar/remediation/{finding_token}-{request_token}-{digest}"
        workspace_path = self.root / digest

        if workspace_path.exists():
            raise FileExistsError("Remediation workspace already exists for this request")

        branch_check = self._run(
            ["git", "-C", str(repository_root), "branch", "--list", branch_name],
            failure="Could not inspect remediation branch state",
        )
        if branch_check.stdout.strip():
            raise FileExistsError("Remediation branch already exists for this request")

        self.root.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                "git",
                "-C",
                str(repository_root),
                "worktree",
                "add",
                "-b",
                branch_name,
                str(workspace_path),
                base_commit,
            ],
            failure="Could not create isolated remediation worktree",
        )

        return PreparedWorkspace(
            request_id=request.request_id,
            repository_root=str(repository_root),
            workspace_path=str(workspace_path),
            branch_name=branch_name,
            base_commit=base_commit,
        )
