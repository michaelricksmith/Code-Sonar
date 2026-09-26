"""Isolated Git worktree preparation for approved remediation requests."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.remediation.approval import RemediationAuthorization
from app.remediation.contracts import RemediationRequest
from app.security import REMEDIATION_WORKTREES_DIR, validate_repo_path

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


GitCommandRunner = Callable[[list[str]], GitCommandResult]


@dataclass(frozen=True, slots=True)
class PreparedWorkspace:
    workspace_id: str
    request_id: str
    repository_root: str
    workspace_path: str
    branch_name: str
    base_commit: str
    scan_id: str = ""
    finding_id: str = ""
    executor: str = ""
    remediation_kind: str = ""
    authorization_id: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return the public workspace identity without exposing host filesystem paths."""
        return {
            "workspace_id": self.workspace_id,
            "request_id": self.request_id,
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
        self.root = root or REMEDIATION_WORKTREES_DIR
        self.runner = runner
        self._prepared: dict[str, PreparedWorkspace] = {}

    def _run(self, args: list[str], *, failure: str) -> GitCommandResult:
        result = self.runner(args)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(failure + suffix)
        return result

    def get(self, workspace_id: str) -> PreparedWorkspace | None:
        """Resolve a server-owned workspace identity to its internal paths."""
        return self._prepared.get(workspace_id)

    def prepare(self, request: RemediationRequest) -> PreparedWorkspace:
        if not request.approved:
            raise PermissionError("Remediation workspace preparation requires explicit approval")

        repo = validate_repo_path(request.repository_path)

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
        workspace_id = "ws_" + hashlib.sha256(
            f"{request.request_id}|{request.finding_id}|{base_commit}|{digest}".encode("utf-8")
        ).hexdigest()[:20]
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

        workspace = PreparedWorkspace(
            workspace_id=workspace_id,
            request_id=request.request_id,
            repository_root=str(repository_root),
            workspace_path=str(workspace_path),
            branch_name=branch_name,
            base_commit=base_commit,
        )
        self._prepared[workspace_id] = workspace
        return workspace

    def prepare_authorized(self, authorization: RemediationAuthorization) -> PreparedWorkspace:
        request = RemediationRequest(
            request_id=authorization.request_id,
            repository_path=authorization.repository_path,
            finding_id=authorization.finding_id,
            scan_id=authorization.scan_id,
            instruction=authorization.instruction,
            approved=True,
        )
        workspace = self.prepare(request)
        if workspace.base_commit != authorization.base_commit:
            self.cleanup(workspace.workspace_id)
            raise PermissionError("Prepared workspace does not match the approved base commit")
        bound = PreparedWorkspace(
            workspace_id=workspace.workspace_id,
            request_id=workspace.request_id,
            repository_root=workspace.repository_root,
            workspace_path=workspace.workspace_path,
            branch_name=workspace.branch_name,
            base_commit=workspace.base_commit,
            scan_id=authorization.scan_id,
            finding_id=authorization.finding_id,
            executor=authorization.executor,
            remediation_kind=authorization.remediation_kind,
            authorization_id=authorization.authorization_id,
        )
        self._prepared[bound.workspace_id] = bound
        return bound

    def cleanup(self, workspace_id: str) -> None:
        """Remove a prepared worktree, its branch, and its in-memory capability."""
        workspace = self._prepared.pop(workspace_id, None)
        if workspace is None:
            return
        workspace_path = Path(workspace.workspace_path).resolve()
        workspace_path.relative_to(self.root.resolve())
        remove_result = self.runner(
            [
                "git",
                "-C",
                workspace.repository_root,
                "worktree",
                "remove",
                "--force",
                workspace.workspace_path,
            ],
        )
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
        branch_result = self.runner(
            ["git", "-C", workspace.repository_root, "branch", "-D", workspace.branch_name],
        )
        if remove_result.returncode != 0 or branch_result.returncode != 0:
            raise RuntimeError("Remediation workspace cleanup did not complete")
