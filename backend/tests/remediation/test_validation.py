"""Tests for app.remediation.validation (unit coverage for the validation module)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.history import InMemoryHistoryStore, build_scan_record
from app.ml.outcomes import JsonlOutcomeStore
from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.remediation.validation import (
    RemediationValidationResult,
    RemediationValidationService,
    ValidationCommand,
    ValidationCommandResult,
    ValidationProcessResult,
    _default_runner,
    resolve_within,
)
from app.scoring.engine import calculate_score
from app.services.repository import AnalyzerExecutionStatus, ScanExecutionResult


def _finding() -> Finding:
    return Finding(
        id="finding-1",
        rule_id="comment_markers:todo",
        category=FindingCategory.MAINTAINABILITY,
        severity=FindingSeverity.WARNING,
        confidence=1.0,
        file_path="src/app.py",
        line_start=1,
        line_end=1,
        symbol=None,
        evidence="TODO: remove",
        message="stale TODO",
        suggestion="remove it",
        debt_points=2,
        remediation_effort="5 minutes",
        analyzer="comment_markers",
        metadata={},
    )


def _history() -> InMemoryHistoryStore:
    store = InMemoryHistoryStore()
    findings = [_finding()]
    store.append(
        build_scan_record(
            repository_id="repo-1",
            repository_path="example/repo",
            findings=findings,
            scoring=calculate_score(findings),
            scan_id="scan-before",
            scanned_at="2026-08-30T20:00:00+00:00",
        )
    )
    return store


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "worktrees"
    workspace = root / "abc123"
    workspace.mkdir(parents=True)
    return root, workspace


def _runner(workspace: Path):
    def run(args: list[str], cwd: Path, timeout: float) -> ValidationProcessResult:
        assert cwd == workspace
        assert timeout > 0
        if args == ["git", "rev-parse", "--show-toplevel"]:
            return ValidationProcessResult(0, stdout=str(workspace))
        if args == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return ValidationProcessResult(
                0, stdout="code-sonar/remediation/finding-1-request-1-abc123\n"
            )
        return ValidationProcessResult(0)

    return run


def _service(tmp_path: Path, **kwargs):
    root, workspace = _workspace(tmp_path)
    defaults = {
        "commands": (),
        "history_store": _history(),
        "outcome_store": JsonlOutcomeStore(tmp_path / "outcomes.jsonl"),
        "workspace_root": root,
        "runner": _runner(workspace),
        "scanner": lambda path: [],
    }
    defaults.update(kwargs)
    service = RemediationValidationService(**defaults)
    return service, workspace


def test_resolve_within_accepts_nested_path(tmp_path: Path) -> None:
    assert resolve_within(tmp_path, "src/app.py") == tmp_path / "src/app.py"


def test_resolve_within_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes the repository"):
        resolve_within(tmp_path, "../outside.py")


def test_validation_command_result_to_dict() -> None:
    result = ValidationCommandResult(name="tests", kind="tests", passed=True, returncode=0)
    assert result.to_dict() == {
        "name": "tests",
        "kind": "tests",
        "passed": True,
        "returncode": 0,
    }


def test_validation_process_result_defaults() -> None:
    result = ValidationProcessResult(returncode=0)
    assert result.stdout == ""
    assert result.stderr == ""


def test_default_runner_captures_success() -> None:
    result = _default_runner([sys.executable, "-c", "print('ok')"], Path.cwd(), 30.0)
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_default_runner_reports_failure() -> None:
    result = _default_runner([sys.executable, "-c", "import sys; sys.exit(3)"], Path.cwd(), 30.0)
    assert result.returncode == 3


def test_default_runner_propagates_timeout() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        _default_runner(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            Path.cwd(),
            0.1,
        )


def test_outcome_id_is_deterministic_and_prefixed() -> None:
    first = RemediationValidationService._outcome_id("r1", "s1", "f1")
    second = RemediationValidationService._outcome_id("r1", "s1", "f1")
    assert first == second
    assert first.startswith("remediation-")
    assert RemediationValidationService._outcome_id("r2", "s1", "f1") != first


def test_aggregate_kind_ignores_other_kinds_and_empty() -> None:
    results = (
        ValidationCommandResult("b", "build", True, 0),
        ValidationCommandResult("t", "tests", False, 1),
    )
    assert RemediationValidationService._aggregate_kind(results, "build") is True
    assert RemediationValidationService._aggregate_kind(results, "tests") is False
    assert RemediationValidationService._aggregate_kind(results, "other") is None
    assert RemediationValidationService._aggregate_kind((), "build") is None


def test_verify_workspace_rejects_missing_directory(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        service._verify_workspace(str(tmp_path / "worktrees" / "missing"))


def test_verify_workspace_rejects_non_worktree(tmp_path: Path) -> None:
    root, workspace = _workspace(tmp_path)

    def run(args: list[str], cwd: Path, timeout: float) -> ValidationProcessResult:
        return ValidationProcessResult(1)

    service = RemediationValidationService(
        history_store=_history(),
        outcome_store=JsonlOutcomeStore(tmp_path / "outcomes.jsonl"),
        workspace_root=root,
        runner=run,
        scanner=lambda path: [],
    )
    with pytest.raises(PermissionError, match="not a Git worktree"):
        service._verify_workspace(str(workspace))


def test_verify_workspace_rejects_wrong_branch(tmp_path: Path) -> None:
    root, workspace = _workspace(tmp_path)

    def run(args: list[str], cwd: Path, timeout: float) -> ValidationProcessResult:
        if args == ["git", "rev-parse", "--show-toplevel"]:
            return ValidationProcessResult(0, stdout=str(workspace))
        return ValidationProcessResult(0, stdout="main\n")

    service = RemediationValidationService(
        history_store=_history(),
        outcome_store=JsonlOutcomeStore(tmp_path / "outcomes.jsonl"),
        workspace_root=root,
        runner=run,
        scanner=lambda path: [],
    )
    with pytest.raises(PermissionError, match="remediation branch"):
        service._verify_workspace(str(workspace))


def test_run_validation_commands_rejects_empty_argv(tmp_path: Path) -> None:
    service, workspace = _service(tmp_path, commands=(ValidationCommand("bad", "build", ()),))
    with pytest.raises(ValueError, match="empty argv"):
        service._run_validation_commands(workspace)


def test_run_validation_commands_maps_timeout_to_124(tmp_path: Path) -> None:
    def run(args: list[str], cwd: Path, timeout: float) -> ValidationProcessResult:
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    service, workspace = _service(
        tmp_path,
        commands=(ValidationCommand("slow", "tests", ("pytest",)),),
        runner=run,
    )
    (result,) = service._run_validation_commands(workspace)
    assert result.passed is False
    assert result.returncode == 124


def test_rescan_findings_rejects_incomplete_scan(tmp_path: Path) -> None:
    incomplete = ScanExecutionResult(
        findings=(),
        analyzers=(
            AnalyzerExecutionStatus(analyzer="comment_markers", status="failed", finding_count=0),
        ),
    )
    service, workspace = _service(tmp_path, scanner=lambda path: incomplete)
    with pytest.raises(RuntimeError, match="incomplete"):
        service._rescan_findings(workspace)


def test_load_before_scan_rejects_unknown_scan(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(LookupError, match="not found"):
        service._load_before_scan("scan-missing", "finding-1")


def test_load_before_scan_rejects_unknown_finding(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(LookupError, match="not present"):
        service._load_before_scan("scan-before", "finding-missing")


def test_validate_unresolved_finding_reports_not_resolved(tmp_path: Path) -> None:
    service, workspace = _service(tmp_path, scanner=lambda path: [_finding()])
    result = service.validate(
        request_id="request-unresolved",
        workspace_path=str(workspace),
        before_scan_id="scan-before",
        finding_id="finding-1",
        executor="cursor",
        remediation_kind="automated_patch",
    )
    assert result.finding_resolved is False
    assert result.regression_detected is False
    assert result.score_delta == 0


def test_validation_result_to_dict_shape(tmp_path: Path) -> None:
    service, workspace = _service(
        tmp_path,
        commands=(ValidationCommand("build", "build", ("make",)),),
        scanner=lambda path: [],
    )
    result = service.validate(
        request_id="request-shape",
        workspace_path=str(workspace),
        before_scan_id="scan-before",
        finding_id="finding-1",
        executor="cursor",
        remediation_kind="automated_patch",
    )
    payload = result.to_dict()
    assert payload["request_id"] == "request-shape"
    assert payload["finding_resolved"] is True
    assert payload["deterministic_score_unchanged_by_ml"] is True
    assert payload["command_results"] == [
        {"name": "build", "kind": "build", "passed": True, "returncode": 0}
    ]
    assert isinstance(result, RemediationValidationResult)
