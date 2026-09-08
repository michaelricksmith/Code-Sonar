"""Run a guarded installed-Cursor remediation proof and emit sanitized evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.history import InMemoryHistoryStore, build_scan_record
from app.ml.outcomes import JsonlOutcomeStore
from app.remediation.approval import RemediationAuthorizationService
from app.remediation.cursor import CursorRemediationExecutor
from app.remediation.orchestration import RemediationOrchestrator
from app.remediation.validation import RemediationValidationService, ValidationCommand
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
        timeout=60,
    )


def _scan(repository: Path):
    result = scan_repository(repository)
    if not isinstance(result, ScanExecutionResult) or not result.complete:
        raise RuntimeError("Code Sonar proof scan was incomplete")
    return list(result.findings)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prove installed Cursor remediation in an isolated Code Sonar worktree."
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="New JSON evidence file. Existing files are never overwritten.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    evidence_path = args.evidence.expanduser().resolve()
    if evidence_path.exists():
        raise FileExistsError(f"Evidence file already exists: {evidence_path}")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    code_sonar_root = Path(__file__).resolve().parents[2]
    code_sonar_commit = _run(
        ["git", "rev-parse", "HEAD"], code_sonar_root
    ).stdout.strip()
    code_sonar_status = _run(
        ["git", "status", "--porcelain"], code_sonar_root
    ).stdout
    if code_sonar_status:
        raise RuntimeError("Code Sonar proof checkout must be clean")

    cursor_version = _run(["agent", "--version"], code_sonar_root).stdout.strip()
    if not cursor_version:
        raise RuntimeError("Cursor Agent CLI version could not be verified")

    proof_root = Path(tempfile.mkdtemp(prefix="code-sonar-cursor-host-proof-"))
    repository = proof_root / "active"
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
    active_hash_before = hashlib.sha256(source.read_bytes()).hexdigest()

    os.environ["CODESONAR_UNSAFE_ALLOW_ANY_SCAN_PATH"] = "1"
    before_findings = _scan(repository)
    target = next(
        finding
        for finding in before_findings
        if finding.analyzer == "comment_markers"
        and Path(finding.file_path).as_posix() == "src/app.py"
    )
    before_scoring = calculate_score(before_findings)
    history = InMemoryHistoryStore()
    history.append(
        build_scan_record(
            repository_id=hashlib.sha256(active_head_before.encode("utf-8")).hexdigest()[:16],
            repository_path="redacted/cursor-proof-fixture",
            findings=before_findings,
            scoring=before_scoring,
            scan_id="cursor-host-proof-before",
        )
    )

    worktree_root = proof_root / "remediation-worktrees"
    workspace_manager = GitWorktreeManager(root=worktree_root)
    executor = CursorRemediationExecutor(
        (
            "agent",
            "-p",
            "--force",
            "--trust",
            "--output-format",
            "text",
            "--workspace",
            "{workspace}",
            "{instruction}",
        ),
        workspace_root=worktree_root,
        timeout_seconds=900,
    )
    validator = RemediationValidationService(
        commands=(
            ValidationCommand(
                name="fixture-pytest",
                kind="tests",
                argv=(sys.executable, "-m", "pytest", "-q"),
                timeout_seconds=300,
            ),
        ),
        history_store=history,
        outcome_store=JsonlOutcomeStore(proof_root / "outcomes.jsonl"),
        workspace_root=worktree_root,
    )
    authorization_service = RemediationAuthorizationService(
        secret="ephemeral-host-proof-secret",
        ttl_seconds=300,
    )
    authorization = authorization_service.issue(
        request_id="cursor-host-proof-request",
        repository_path=str(repository),
        scan_id="cursor-host-proof-before",
        finding_id=target.id,
        plan_id="cursor-host-proof-plan",
        executor="cursor",
        remediation_kind="automated_patch",
        instruction=(
            "Resolve only the Code Sonar TODO finding in src/app.py. "
            "Remove the TODO comment without changing program behavior, tests, "
            "configuration, dependencies, Git state, or any other file."
        ),
    )
    orchestrator = RemediationOrchestrator(
        workspace_manager=workspace_manager,
        executor=executor,
        validation_service=validator,
        authorization_service=authorization_service,
    )
    result = orchestrator.run_authorized(authorization)
    if result.workspace is None or result.execution is None or result.validation is None:
        raise RuntimeError("Cursor remediation workflow did not reach validation")

    active_head_after = _run(["git", "rev-parse", "HEAD"], repository).stdout.strip()
    active_status_after = _run(["git", "status", "--porcelain"], repository).stdout
    active_hash_after = hashlib.sha256(source.read_bytes()).hexdigest()
    branch_remaining = _run(
        ["git", "branch", "--list", result.workspace.branch_name], repository
    ).stdout.strip()

    validation = result.validation
    checkout_isolated = (
        active_head_after == active_head_before
        and active_status_after == active_status_before
        and active_hash_after == active_hash_before
    )
    cleanup_completed = (
        not Path(result.workspace.workspace_path).exists()
        and workspace_manager.get(result.workspace.workspace_id) is None
        and not branch_remaining
    )
    changed_files_exact = result.execution.changed_files == ("src/app.py",)
    successful = all(
        (
            result.execution.executor_name == "cursor",
            changed_files_exact,
            validation.tests_passed is True,
            validation.finding_resolved,
            not validation.regression_detected,
            validation.score_delta > 0,
            validation.debt_points_delta < 0,
            checkout_isolated,
            cleanup_completed,
        )
    )

    evidence = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_sonar_commit": code_sonar_commit,
        "cursor_version": cursor_version,
        "executor": result.execution.executor_name,
        "repository_id": hashlib.sha256(active_head_before.encode("utf-8")).hexdigest()[:16],
        "before_scan_id": validation.before_scan_id,
        "after_scan_id": validation.after_scan_id,
        "branch_name": result.workspace.branch_name,
        "base_commit": result.workspace.base_commit,
        "changed_files": list(result.execution.changed_files),
        "validation_commands": [
            command.to_dict() for command in validation.command_results
        ],
        "finding_resolved": validation.finding_resolved,
        "regression_detected": validation.regression_detected,
        "score_delta": validation.score_delta,
        "debt_points_delta": validation.debt_points_delta,
        "training_label_value": validation.training_label_value,
        "active_checkout": {
            "head_unchanged": active_head_after == active_head_before,
            "status_unchanged": active_status_after == active_status_before,
            "target_hash_unchanged": active_hash_after == active_hash_before,
        },
        "cleanup": {
            "worktree_removed": not Path(result.workspace.workspace_path).exists(),
            "branch_removed": not branch_remaining,
            "manager_state_removed": (
                workspace_manager.get(result.workspace.workspace_id) is None
            ),
        },
        "successful": successful,
    }
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print(f"Sanitized evidence written to: {evidence_path}")
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
