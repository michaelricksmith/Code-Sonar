"""Validation and rescan loop for completed remediation attempts."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from app.history import HistoryStore, JsonlHistoryStore, build_scan_record
from app.ml.outcomes import JsonlOutcomeStore, RemediationOutcome
from app.ml.outcomes.labels import remediation_success_label
from app.models.finding import Finding
from app.scoring.engine import calculate_score
from app.services.repository import scan_repository

ValidationKind = Literal["build", "tests", "other"]


@dataclass(frozen=True, slots=True)
class ValidationCommand:
    name: str
    kind: ValidationKind
    argv: tuple[str, ...]
    timeout_seconds: float = 300.0


@dataclass(frozen=True, slots=True)
class ValidationCommandResult:
    name: str
    kind: ValidationKind
    passed: bool
    returncode: int

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "passed": self.passed,
            "returncode": self.returncode,
        }


@dataclass(frozen=True, slots=True)
class ValidationProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


ValidationRunner = Callable[[list[str], Path, float], ValidationProcessResult]
Scanner = Callable[[Path], list[Finding]]


def _default_runner(args: list[str], cwd: Path, timeout: float) -> ValidationProcessResult:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return ValidationProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


@dataclass(frozen=True, slots=True)
class RemediationValidationResult:
    request_id: str
    before_scan_id: str
    after_scan_id: str
    outcome_id: str
    finding_resolved: bool
    regression_detected: bool
    score_delta: int
    debt_points_delta: int
    build_passed: bool | None
    tests_passed: bool | None
    command_results: tuple[ValidationCommandResult, ...]
    training_label_value: str
    training_label_trust_tier: str

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "before_scan_id": self.before_scan_id,
            "after_scan_id": self.after_scan_id,
            "outcome_id": self.outcome_id,
            "finding_resolved": self.finding_resolved,
            "regression_detected": self.regression_detected,
            "score_delta": self.score_delta,
            "debt_points_delta": self.debt_points_delta,
            "build_passed": self.build_passed,
            "tests_passed": self.tests_passed,
            "command_results": [result.to_dict() for result in self.command_results],
            "training_label_value": self.training_label_value,
            "training_label_trust_tier": self.training_label_trust_tier,
            "deterministic_score_unchanged_by_ml": True,
        }


class RemediationValidationService:
    """Validate one isolated worktree, rescan it, and persist observed outcome evidence."""

    def __init__(
        self,
        *,
        commands: tuple[ValidationCommand, ...] = (),
        history_store: HistoryStore | None = None,
        outcome_store: JsonlOutcomeStore | None = None,
        workspace_root: Path | None = None,
        runner: ValidationRunner = _default_runner,
        scanner: Scanner = scan_repository,
    ) -> None:
        self.commands = commands
        self.history_store = history_store or JsonlHistoryStore()
        self.outcome_store = outcome_store or JsonlOutcomeStore()
        self.workspace_root = (
            workspace_root or (Path.home() / ".code-sonar" / "remediation-worktrees")
        ).expanduser().resolve()
        self.runner = runner
        self.scanner = scanner

    def _verify_workspace(self, workspace_path: str) -> Path:
        workspace = Path(workspace_path).expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError("Remediation validation workspace does not exist")
        try:
            workspace.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionError(
                "Remediation validation may run only inside Code Sonar remediation worktrees"
            ) from exc
        return workspace

    @staticmethod
    def _aggregate_kind(
        results: tuple[ValidationCommandResult, ...], kind: ValidationKind
    ) -> bool | None:
        relevant = [result.passed for result in results if result.kind == kind]
        return None if not relevant else all(relevant)

    def validate(
        self,
        *,
        request_id: str,
        workspace_path: str,
        before_scan_id: str,
        finding_id: str,
        executor: str,
        remediation_kind: str,
        attempted_at: str | None = None,
    ) -> RemediationValidationResult:
        workspace = self._verify_workspace(workspace_path)
        before = self.history_store.get(before_scan_id)
        if before is None:
            raise LookupError("Original persisted scan was not found")
        if not any(finding.id == finding_id for finding in before.findings):
            raise LookupError("Target finding was not present in the original scan")

        command_results: list[ValidationCommandResult] = []
        for command in self.commands:
            if not command.argv:
                raise ValueError(f"Validation command {command.name!r} has empty argv")
            try:
                result = self.runner(list(command.argv), workspace, command.timeout_seconds)
                returncode = result.returncode
            except subprocess.TimeoutExpired:
                returncode = 124
            command_results.append(
                ValidationCommandResult(
                    name=command.name,
                    kind=command.kind,
                    passed=returncode == 0,
                    returncode=returncode,
                )
            )

        command_tuple = tuple(command_results)
        build_passed = self._aggregate_kind(command_tuple, "build")
        tests_passed = self._aggregate_kind(command_tuple, "tests")

        findings = self.scanner(workspace)
        scoring = calculate_score(findings)
        after = build_scan_record(
            repository_id=before.repository_id,
            repository_path=before.repository_path,
            findings=findings,
            scoring=scoring,
        )
        self.history_store.append(after)

        finding_resolved = not any(finding.id == finding_id for finding in after.findings)
        score_delta = after.score - before.score
        debt_points_delta = after.total_debt_points - before.total_debt_points
        regression_detected = score_delta < 0 or debt_points_delta > 0
        attempted = attempted_at or datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(
            f"{request_id}|{before.scan_id}|{after.scan_id}|{finding_id}".encode("utf-8")
        ).hexdigest()[:20]
        outcome_id = f"remediation-{digest}"
        if self.outcome_store.get(outcome_id) is not None:
            raise FileExistsError("Remediation outcome already exists")

        outcome = RemediationOutcome(
            outcome_id=outcome_id,
            repository_id=before.repository_id,
            finding_id=finding_id,
            before_scan_id=before.scan_id,
            after_scan_id=after.scan_id,
            attempted_at=attempted,
            executor=executor,
            remediation_kind=remediation_kind,
            build_passed=build_passed,
            tests_passed=tests_passed,
            finding_resolved=finding_resolved,
            regression_detected=regression_detected,
            score_delta=score_delta,
            debt_points_delta=debt_points_delta,
        )
        self.outcome_store.append(outcome)
        label = remediation_success_label(outcome)

        return RemediationValidationResult(
            request_id=request_id,
            before_scan_id=before.scan_id,
            after_scan_id=after.scan_id,
            outcome_id=outcome_id,
            finding_resolved=finding_resolved,
            regression_detected=regression_detected,
            score_delta=score_delta,
            debt_points_delta=debt_points_delta,
            build_passed=build_passed,
            tests_passed=tests_passed,
            command_results=command_tuple,
            training_label_value=label.value,
            training_label_trust_tier=label.trust_tier.value,
        )
