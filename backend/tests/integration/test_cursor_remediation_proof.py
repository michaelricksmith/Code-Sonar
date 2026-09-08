"""Concrete end-to-end proof of the controlled Cursor remediation workflow.

The Cursor binary boundary is deterministic in CI; every other layer uses its real
implementation, including Git worktrees, authorization, validation commands,
repository rescanning, deterministic scoring, outcome persistence, and cleanup.
A separate operator run is required before claiming that an installed Cursor CLI
successfully completed the same workflow.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.history import InMemoryHistoryStore, build_scan_record
from app.ml.outcomes import JsonlOutcomeStore
from app.remediation.approval import RemediationAuthorizationService
from app.remediation.cursor import CursorRemediationExecutor, ProcessResult
from app.remediation.orchestration import RemediationOrchestrator
from app.remediation.validation import (
    RemediationValidationService,
    ValidationCommand,
    ValidationProcessResult,
)
from app.remediation.workspace import GitWorktreeManager
from app.scoring.engine import calculate_score
from app.services.repository import ScanExecutionResult, scan_repository


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _scan_findings(repository: Path):
    result = scan_repository(repository)
    assert isinstance(result, ScanExecutionResult)
    assert result.complete is True
    return list(result.findings)


def test_cursor_workflow_proves_isolation_tests_rescan_and_improvement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CODESONAR_UNSAFE_ALLOW_ANY_SCAN_PATH", "1")
    repository = tmp_path / "active"
    repository.mkdir()
    (repository / "src").mkdir()
    (repository / "tests").mkdir()
    (repository / "src" / "__init__.py").write_text("", encoding="utf-8")
    source = repository / "src" / "app.py"
    source.write_text(
        "def answer() -> int:\n"
        "    # TODO: remove this tracked remediation target\n"
        "    return 42\n",
        encoding="utf-8",
    )
    (repository / "tests" / "test_app.py").write_text(
        "from src.app import answer\n\n"
        "def test_answer() -> None:\n"
        "    assert answer() == 42\n",
        encoding="utf-8",
    )

    _run(["git", "init"], repository)
    _run(["git", "config", "user.name", "Code Sonar Proof"], repository)
    _run(["git", "config", "user.email", "proof@code-sonar.local"], repository)
    _run(["git", "add", "."], repository)
    _run(["git", "commit", "-m", "proof baseline"], repository)

    active_head_before = _run(["git", "rev-parse", "HEAD"], repository).stdout.strip()
    active_status_before = _run(["git", "status", "--porcelain"], repository).stdout
    active_source_before = source.read_bytes()

    before_findings = _scan_findings(repository)
    target = next(
        finding
        for finding in before_findings
        if finding.analyzer == "comment_markers"
        and Path(finding.file_path).as_posix() == "src/app.py"
    )
    history = InMemoryHistoryStore()
    history.append(
        build_scan_record(
            repository_id="cursor-proof-repository",
            repository_path="redacted/proof-repository",
            findings=before_findings,
            scoring=calculate_score(before_findings),
            scan_id="cursor-proof-before",
            scanned_at="2026-09-08T00:00:00+00:00",
        )
    )

    worktree_root = tmp_path / "remediation-worktrees"
    workspace_manager = GitWorktreeManager(root=worktree_root)

    def cursor_runner(args: list[str], cwd: Path, timeout: float) -> ProcessResult:
        assert timeout > 0
        if args[0] == "cursor-proof-agent":
            assert args[1] == str(cwd)
            assert target.id in args[2]
            candidate = cwd / "src" / "app.py"
            candidate.write_text(
                candidate.read_text(encoding="utf-8").replace(
                    "    # TODO: remove this tracked remediation target\n", ""
                ),
                encoding="utf-8",
            )
            return ProcessResult(0, stdout="deterministic Cursor boundary completed")
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ProcessResult(completed.returncode, completed.stdout, completed.stderr)

    def validation_runner(
        args: list[str], cwd: Path, timeout: float
    ) -> ValidationProcessResult:
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ValidationProcessResult(
            completed.returncode, completed.stdout, completed.stderr
        )

    executor = CursorRemediationExecutor(
        ("cursor-proof-agent", "{workspace}", "{instruction}"),
        workspace_root=worktree_root,
        runner=cursor_runner,
    )
    validator = RemediationValidationService(
        commands=(
            ValidationCommand(
                name="proof-tests",
                kind="tests",
                argv=(sys.executable, "-m", "pytest", "-q"),
            ),
        ),
        history_store=history,
        outcome_store=JsonlOutcomeStore(tmp_path / "outcomes.jsonl"),
        workspace_root=worktree_root,
        runner=validation_runner,
    )
    authorization_service = RemediationAuthorizationService(
        secret="cursor-proof-secret",
        ttl_seconds=300,
    )
    authorization = authorization_service.issue(
        request_id="cursor-proof-request",
        repository_path=str(repository),
        scan_id="cursor-proof-before",
        finding_id=target.id,
        plan_id="cursor-proof-plan",
        executor="cursor",
        remediation_kind="automated_patch",
        instruction=f"Resolve Code Sonar finding {target.id} without changing behavior.",
    )
    orchestrator = RemediationOrchestrator(
        workspace_manager=workspace_manager,
        executor=executor,
        validation_service=validator,
        authorization_service=authorization_service,
    )

    result = orchestrator.run_authorized(authorization)

    assert result.execution is not None
    assert result.execution.executor_name == "cursor"
    assert result.execution.changed_files == ("src/app.py",)
    assert result.validation is not None
    assert result.validation.tests_passed is True
    assert result.validation.finding_resolved is True
    assert result.validation.regression_detected is False
    assert result.validation.score_delta > 0
    assert result.validation.debt_points_delta < 0
    assert result.validation.training_label_value == "1"

    assert result.workspace is not None
    assert result.workspace.branch_name.startswith("code-sonar/remediation/")
    assert not Path(result.workspace.workspace_path).exists()
    assert workspace_manager.get(result.workspace.workspace_id) is None
    branch = _run(
        ["git", "branch", "--list", result.workspace.branch_name], repository
    ).stdout
    assert branch.strip() == ""

    assert _run(["git", "rev-parse", "HEAD"], repository).stdout.strip() == active_head_before
    assert _run(["git", "status", "--porcelain"], repository).stdout == active_status_before
    assert source.read_bytes() == active_source_before
