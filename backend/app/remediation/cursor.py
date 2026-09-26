"""Cursor-oriented remediation executor constrained to Code Sonar worktrees."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.remediation.contracts import (
    RemediationExecutionResult,
    RemediationExecutionState,
    RemediationRequest,
)
from app.security import REMEDIATION_WORKTREES_DIR


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


ProcessRunner = Callable[[list[str], Path, float], ProcessResult]


def _default_process_runner(args: list[str], cwd: Path, timeout: float) -> ProcessResult:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return ProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


class CursorRemediationExecutor:
    """Run an explicitly configured Cursor command inside one isolated worktree.

    The command is supplied as an argv template, never a shell string. Only the
    ``{workspace}`` and ``{instruction}`` placeholders are substituted. Code Sonar
    verifies that the target directory is inside its remediation-worktree root and
    is currently on a ``code-sonar/remediation/`` branch before invoking Cursor.
    """

    executor_name = "cursor"

    def __init__(
        self,
        command_template: tuple[str, ...],
        *,
        workspace_root: Path | None = None,
        runner: ProcessRunner = _default_process_runner,
        timeout_seconds: float = 900.0,
    ) -> None:
        if not command_template:
            raise ValueError("Cursor command template must not be empty")
        joined = "\n".join(command_template)
        if "{workspace}" not in joined or "{instruction}" not in joined:
            raise ValueError(
                "Cursor command template must include {workspace} and {instruction}"
            )
        self.command_template = command_template
        self.workspace_root = (
            workspace_root or REMEDIATION_WORKTREES_DIR
        ).expanduser().resolve()
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def _run(
        self,
        args: list[str],
        cwd: Path,
        *,
        timeout: float = 30.0,
        failure: str,
    ) -> ProcessResult:
        result = self.runner(args, cwd, timeout)
        if result.returncode != 0:
            raise RuntimeError(f"{failure} (exit code {result.returncode})")
        return result

    def _verified_workspace(self, repository_path: str) -> Path:
        workspace = Path(repository_path).expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError("Prepared remediation workspace does not exist")
        try:
            workspace.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionError(
                "Cursor remediation may run only inside Code Sonar remediation worktrees"
            ) from exc

        top_level = self._run(
            ["git", "rev-parse", "--show-toplevel"],
            workspace,
            failure="Could not verify remediation Git worktree",
        ).stdout.strip()
        if not top_level or Path(top_level).resolve() != workspace:
            raise PermissionError("Cursor target is not the prepared remediation worktree root")

        branch = self._run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            workspace,
            failure="Could not verify remediation branch",
        ).stdout.strip()
        if not branch.startswith("code-sonar/remediation/"):
            raise PermissionError("Cursor target is not on a Code Sonar remediation branch")
        return workspace

    def _changed_files(self, workspace: Path) -> tuple[str, ...]:
        tracked = self._run(
            ["git", "diff", "--name-only", "HEAD"],
            workspace,
            failure="Could not inspect remediation changes",
        ).stdout.splitlines()
        untracked = self._run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            workspace,
            failure="Could not inspect untracked remediation changes",
        ).stdout.splitlines()
        return tuple(sorted({path.strip() for path in [*tracked, *untracked] if path.strip()}))

    def execute(self, request: RemediationRequest) -> RemediationExecutionResult:
        if not request.approved:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.DRY_RUN,
                summary="Cursor execution requires explicit approval; no command was run.",
            )

        try:
            workspace = self._verified_workspace(request.repository_path)
            command = [
                token.replace("{workspace}", str(workspace)).replace(
                    "{instruction}", request.instruction
                )
                for token in self.command_template
            ]
            result = self.runner(command, workspace, self.timeout_seconds)
            if result.returncode != 0:
                return RemediationExecutionResult(
                    request_id=request.request_id,
                    executor_name=self.executor_name,
                    state=RemediationExecutionState.FAILED,
                    summary="Cursor remediation command failed.",
                    error=f"Cursor command exited with code {result.returncode}",
                )
            changed_files = self._changed_files(workspace)
        except (PermissionError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                summary="Cursor remediation was blocked before validation.",
                error=str(exc),
            )

        return RemediationExecutionResult(
            request_id=request.request_id,
            executor_name=self.executor_name,
            state=RemediationExecutionState.EXECUTED,
            changed_files=changed_files,
            summary=(
                "Cursor remediation command completed inside the isolated worktree; "
                f"Code Sonar observed {len(changed_files)} changed file(s)."
            ),
        )
