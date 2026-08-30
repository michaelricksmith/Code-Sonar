"""Tests for remediation validation, rescan, and outcome-label capture."""

from pathlib import Path

import pytest

from app.history import InMemoryHistoryStore, build_scan_record
from app.ml.outcomes import JsonlOutcomeStore
from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.remediation.validation import (
    RemediationValidationService,
    ValidationCommand,
    ValidationProcessResult,
)
from app.scoring.engine import calculate_score


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


def _runner(workspace: Path, *, tests_returncode: int = 0):
    def run(args: list[str], cwd: Path, timeout: float) -> ValidationProcessResult:
        assert cwd == workspace
        assert timeout > 0
        if args == ["git", "rev-parse", "--show-toplevel"]:
            return ValidationProcessResult(0, stdout=str(workspace))
        if args == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return ValidationProcessResult(
                0, stdout="code-sonar/remediation/finding-1-request-1-abc123\n"
            )
        if args == ["python", "-m", "pytest"]:
            return ValidationProcessResult(tests_returncode)
        if args == ["python", "-m", "build"]:
            return ValidationProcessResult(0)
        raise AssertionError(f"Unexpected command: {args!r}")

    return run


def test_resolved_finding_with_passing_validation_creates_high_trust_label(
    tmp_path: Path,
) -> None:
    root, workspace = _workspace(tmp_path)
    history = _history()
    outcomes = JsonlOutcomeStore(tmp_path / "outcomes.jsonl")
    service = RemediationValidationService(
        commands=(
            ValidationCommand("tests", "tests", ("python", "-m", "pytest")),
            ValidationCommand("build", "build", ("python", "-m", "build")),
        ),
        history_store=history,
        outcome_store=outcomes,
        workspace_root=root,
        runner=_runner(workspace),
        scanner=lambda path: [],
    )

    result = service.validate(
        request_id="request-1",
        workspace_path=str(workspace),
        before_scan_id="scan-before",
        finding_id="finding-1",
        executor="cursor",
        remediation_kind="automated_patch",
        attempted_at="2026-08-30T21:00:00+00:00",
    )

    assert result.finding_resolved is True
    assert result.build_passed is True
    assert result.tests_passed is True
    assert result.regression_detected is False
    assert result.score_delta > 0
    assert result.debt_points_delta < 0
    assert result.training_label_value == "1"
    assert result.training_label_trust_tier == "remediation_outcome"
    assert len(history.load_all("repo-1")) == 2
    stored = outcomes.get(result.outcome_id)
    assert stored is not None
    assert stored.successful is True
    assert stored.before_scan_id == "scan-before"
    assert stored.after_scan_id == result.after_scan_id


def test_failed_tests_force_unsuccessful_label_even_when_finding_resolves(
    tmp_path: Path,
) -> None:
    root, workspace = _workspace(tmp_path)
    outcomes = JsonlOutcomeStore(tmp_path / "outcomes.jsonl")
    service = RemediationValidationService(
        commands=(
            ValidationCommand("tests", "tests", ("python", "-m", "pytest")),
        ),
        history_store=_history(),
        outcome_store=outcomes,
        workspace_root=root,
        runner=_runner(workspace, tests_returncode=1),
        scanner=lambda path: [],
    )

    result = service.validate(
        request_id="request-2",
        workspace_path=str(workspace),
        before_scan_id="scan-before",
        finding_id="finding-1",
        executor="cursor",
        remediation_kind="automated_patch",
    )

    assert result.finding_resolved is True
    assert result.tests_passed is False
    assert result.training_label_value == "0"
    stored = outcomes.get(result.outcome_id)
    assert stored is not None
    assert stored.successful is False


def test_duplicate_request_is_rejected_before_second_rescan(tmp_path: Path) -> None:
    root, workspace = _workspace(tmp_path)
    history = _history()
    service = RemediationValidationService(
        history_store=history,
        outcome_store=JsonlOutcomeStore(tmp_path / "outcomes.jsonl"),
        workspace_root=root,
        runner=_runner(workspace),
        scanner=lambda path: [],
    )
    kwargs = {
        "request_id": "request-duplicate",
        "workspace_path": str(workspace),
        "before_scan_id": "scan-before",
        "finding_id": "finding-1",
        "executor": "cursor",
        "remediation_kind": "automated_patch",
    }

    service.validate(**kwargs)
    assert len(history.load_all("repo-1")) == 2

    with pytest.raises(FileExistsError, match="already exists"):
        service.validate(**kwargs)

    assert len(history.load_all("repo-1")) == 2


def test_validation_rejects_workspace_outside_managed_root(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    service = RemediationValidationService(
        history_store=_history(),
        outcome_store=JsonlOutcomeStore(tmp_path / "outcomes.jsonl"),
        workspace_root=root,
        runner=lambda args, cwd, timeout: ValidationProcessResult(0),
        scanner=lambda path: [],
    )

    with pytest.raises(PermissionError, match="only inside"):
        service.validate(
            request_id="request-outside",
            workspace_path=str(outside),
            before_scan_id="scan-before",
            finding_id="finding-1",
            executor="cursor",
            remediation_kind="automated_patch",
        )
